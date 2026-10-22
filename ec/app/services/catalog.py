from decimal import Decimal
from urllib.parse import urlencode
from django.db.models import Avg, Count, FloatField, Q
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from ..models import Product, CATEGORY_CHOICES

SORT_OPTIONS = {
    'newest': {
        'label': 'Newest Arrivals',
        'order_by': ['-id'],
    },
    'price_low': {
        'label': 'Price: Low to High',
        'order_by': ['discounted_price', 'id'],
    },
    'price_high': {
        'label': 'Price: High to Low',
        'order_by': ['-discounted_price', 'id'],
    },
    'name_asc': {
        'label': 'Name: A to Z',
        'order_by': ['title', 'id'],
    },
    'rating_desc': {
        'label': 'Rating: High to Low',
        'order_by': ['-avg_rating', '-id'],
    },
}

DEFAULT_SORT = 'newest'
DEFAULT_PAGE_SIZE = 12

CATEGORY_MAP = dict(CATEGORY_CHOICES)
CATEGORY_ALIASES = {
    'CH': 'CZ',  # Alias Cheese 'CH' to 'CZ'
}


def clean_catalog_params(params, base_category=None):
    """
    Validates and normalizes catalog search, filter, and sort parameters.
    Works with request.GET (QueryDict) or a standard dictionary.
    """
    cleaned = {
        'q': '',
        'category': '',
        'min_price': None,
        'max_price': None,
        'in_stock': False,
        'rating': None,
        'sort': DEFAULT_SORT,
        'page': 1,
        'errors': [],
    }

    # 1. Search keyword
    raw_q = params.get('q', '')
    if raw_q:
        cleaned['q'] = str(raw_q).strip()

    # 2. Category selection
    cat = (base_category or params.get('category', '')).strip().upper()
    if cat in CATEGORY_ALIASES:
        cat = CATEGORY_ALIASES[cat]
    if cat and cat in CATEGORY_MAP:
        cleaned['category'] = cat
    elif cat and cat.lower() not in ['all', '']:
        cleaned['category'] = cat
    else:
        cleaned['category'] = ''

    # 3. Numeric Price Bounds (against discounted_price)
    raw_min = params.get('min_price', '').strip()
    raw_max = params.get('max_price', '').strip()

    parsed_min = None
    parsed_max = None

    if raw_min:
        try:
            val_min = float(raw_min)
            if val_min < 0:
                cleaned['errors'].append("Minimum price cannot be negative.")
            else:
                parsed_min = round(val_min, 2)
        except (ValueError, TypeError):
            cleaned['errors'].append("Minimum price must be a valid number.")

    if raw_max:
        try:
            val_max = float(raw_max)
            if val_max < 0:
                cleaned['errors'].append("Maximum price cannot be negative.")
            else:
                parsed_max = round(val_max, 2)
        except (ValueError, TypeError):
            cleaned['errors'].append("Maximum price must be a valid number.")

    if parsed_min is not None and parsed_max is not None:
        if parsed_min > parsed_max:
            cleaned['errors'].append("Minimum price cannot be greater than maximum price.")
            parsed_min = None
            parsed_max = None

    cleaned['min_price'] = parsed_min
    cleaned['max_price'] = parsed_max

    # 4. In-Stock Availability
    raw_stock = params.get('in_stock', '').strip().lower()
    if raw_stock in ['1', 'true', 'yes', 'on']:
        cleaned['in_stock'] = True

    # 5. Rating Threshold (1 to 5)
    raw_rating = params.get('rating', '').strip()
    if raw_rating:
        try:
            r_val = float(raw_rating)
            if 1 <= r_val <= 5:
                cleaned['rating'] = r_val
            else:
                cleaned['errors'].append("Rating filter must be between 1 and 5.")
        except (ValueError, TypeError):
            cleaned['errors'].append("Rating must be a valid number.")

    # 6. Sorting allowlist
    raw_sort = params.get('sort', '').strip().lower()
    if raw_sort in SORT_OPTIONS:
        cleaned['sort'] = raw_sort
    else:
        cleaned['sort'] = DEFAULT_SORT

    # 7. Pagination page number
    raw_page = params.get('page', 1)
    try:
        p_val = int(raw_page)
        cleaned['page'] = p_val if p_val > 0 else 1
    except (ValueError, TypeError):
        cleaned['page'] = 1

    return cleaned


def get_catalog_queryset(cleaned_params):
    """
    Builds annotated, filtered, and sorted Product queryset.
    Annotates avg_rating and approved_review_count using only APPROVED reviews.
    """
    qs = Product.objects.all()

    # Annotate approved review statistics for rating display, sorting, and filtering
    qs = qs.annotate(
        avg_rating=Coalesce(
            Avg('reviews__rating', filter=Q(reviews__status='APPROVED')),
            0.0,
            output_field=FloatField()
        ),
        approved_review_count=Count(
            'reviews',
            filter=Q(reviews__status='APPROVED')
        )
    )

    # Search filter (title or description, case-insensitive partial match)
    q = cleaned_params.get('q')
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    # Category filter
    category = cleaned_params.get('category')
    if category:
        qs = qs.filter(category=category)

    # Price range filters (discounted_price is the checkout price)
    min_price = cleaned_params.get('min_price')
    if min_price is not None:
        qs = qs.filter(discounted_price__gte=min_price)

    max_price = cleaned_params.get('max_price')
    if max_price is not None:
        qs = qs.filter(discounted_price__lte=max_price)

    # In-stock filter
    if cleaned_params.get('in_stock'):
        qs = qs.filter(stock__gt=0)

    # Minimum rating filter
    rating = cleaned_params.get('rating')
    if rating is not None:
        qs = qs.filter(avg_rating__gte=rating)

    # Deterministic sorting
    sort_key = cleaned_params.get('sort', DEFAULT_SORT)
    order_fields = SORT_OPTIONS.get(sort_key, SORT_OPTIONS[DEFAULT_SORT])['order_by']
    qs = qs.order_by(*order_fields)

    return qs


def paginate_catalog(queryset, page_number, page_size=DEFAULT_PAGE_SIZE):
    """
    Paginates the queryset, safely handling non-integer or out-of-range pages.
    """
    paginator = Paginator(queryset, page_size)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages if paginator.num_pages > 0 else 1)

    return page_obj, paginator


def build_preserved_query_params(request_get, exclude_keys=('page',)):
    """
    Builds URL-encoded query string preserving all active filters and sort parameters,
    omitting keys specified in exclude_keys.
    """
    params = []
    if hasattr(request_get, 'lists'):
        items = request_get.lists()
    else:
        items = [(k, [v] if not isinstance(v, list) else v) for k, v in request_get.items()]

    for key, values in items:
        if key in exclude_keys:
            continue
        for val in values:
            if val is not None and str(val).strip() != '':
                params.append((key, str(val).strip()))

    return urlencode(params)


def get_active_filters(cleaned_params):
    """
    Returns structured list of active filters for UI badges/tags.
    """
    active = []

    if cleaned_params.get('q'):
        active.append({
            'type': 'q',
            'label': f'Search: "{cleaned_params["q"]}"',
            'param': 'q',
        })

    if cleaned_params.get('category'):
        cat_name = CATEGORY_MAP.get(cleaned_params['category'], cleaned_params['category'])
        active.append({
            'type': 'category',
            'label': f'Category: {cat_name}',
            'param': 'category',
        })

    min_p = cleaned_params.get('min_price')
    max_p = cleaned_params.get('max_price')
    if min_p is not None and max_p is not None:
        active.append({
            'type': 'price',
            'label': f'Price: ৳{min_p} - ৳{max_p}',
            'param': 'price',
        })
    elif min_p is not None:
        active.append({
            'type': 'min_price',
            'label': f'Min: ৳{min_p}',
            'param': 'min_price',
        })
    elif max_p is not None:
        active.append({
            'type': 'max_price',
            'label': f'Max: ৳{max_p}',
            'param': 'max_price',
        })

    if cleaned_params.get('in_stock'):
        active.append({
            'type': 'in_stock',
            'label': 'In Stock Only',
            'param': 'in_stock',
        })

    if cleaned_params.get('rating'):
        active.append({
            'type': 'rating',
            'label': f'Rating: {cleaned_params["rating"]}★ & above',
            'param': 'rating',
        })

    return active

