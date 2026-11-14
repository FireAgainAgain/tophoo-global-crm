"""Customer grade labels; independent commercial grades A-E and product matches A-D."""

GRADE_NAMES = {'A': '订单客户', 'B': '样单客户', 'C': '重潜客户', 'D': '普潜客户', 'E': '无潜客户'}
PRODUCT_MATCH_NAMES = {'A': '对口', 'B': '小对口', 'C': '配件', 'D': '不对口'}


def customer_grade_label(grade):
    if not grade:
        return '未分级 · 待评估'
    name = GRADE_NAMES.get(grade)
    return f'{grade} · {name}' if name else str(grade)


def product_match_label(value):
    return f'{value} · {PRODUCT_MATCH_NAMES[value]}' if value in PRODUCT_MATCH_NAMES else '未评估'
