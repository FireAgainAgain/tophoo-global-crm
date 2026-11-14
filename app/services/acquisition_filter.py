"""Conservative, deterministic qualification without quality scores."""

import re
import unicodedata


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


COUNTRY_ALIASES = {
    "德国": ("de", "deu", "germany", "deutschland"),
    "美国": ("us", "usa", "united states", "united states of america"),
    "英国": ("uk", "gb", "gbr", "united kingdom", "great britain"),
    "中国": ("cn", "chn", "china", "中国大陆"),
    "法国": ("fr", "fra", "france"), "意大利": ("it", "ita", "italy"),
    "西班牙": ("es", "esp", "spain"), "加拿大": ("ca", "can", "canada"),
    "澳大利亚": ("au", "aus", "australia"), "印度": ("in", "ind", "india"),
    "日本": ("jp", "jpn", "japan"), "韩国": ("kr", "kor", "south korea"),
    "阿联酋": ("ae", "are", "uae", "united arab emirates"),
    "巴西": ("br", "bra", "brazil"), "墨西哥": ("mx", "mex", "mexico"),
}
TYPE_ALIASES = {
    "distributor": ("distributors", "经销商", "分销商"),
    "importer": ("importers", "进口商"),
    "manufacturer": ("manufacturers", "生产厂家", "制造商", "生产商"),
    "supplier": ("suppliers", "供应商"),
    "wholesaler": ("wholesalers", "批发商"),
    "retailer": ("retailers", "零售商"),
}


def canonical(value, aliases):
    value = normalized(value)
    for key, variants in aliases.items():
        if value == normalized(key) or value in variants:
            return key
    return value


def terms(value):
    values = re.split(r"[,，\n]", value) if isinstance(value, str) else value
    return list(dict.fromkeys(normalized(item) for item in values if normalized(item)))


def contains(text, term):
    # English words use word boundaries; CJK phrases use literal matching.
    if re.search(r"[\u3400-\u9fff]", term):
        return term in text
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))

def keyword_matches(text,term):
    """Match complete product words, including plural and hyphenated variants."""
    if contains(text,term):return True
    if re.search(r'[\u3400-\u9fff]',term):return False
    def stem(word):
        if word=='finned':return 'fin'
        if len(word)>3 and word.endswith('s') and not word.endswith('ss'):return word[:-1]
        return word
    wanted={stem(word) for word in re.findall(r'[a-z0-9]+',term)}
    actual={stem(word) for word in re.findall(r'[a-z0-9]+',text)}
    return bool(wanted) and wanted<=actual


def qualify(item, countries, types, industries, keyword, excluded, external=False):
    text = normalized(" ".join(filter(None, [item.company_name, item.description, item.company_type])))
    pending, rejected = [], []
    if any(contains(text, term) for term in excluded):
        return "filtered", "命中排除关键词"
    if countries:
        actual = canonical(item.country, COUNTRY_ALIASES)
        if not actual:
            pending.append("国家 / 地区信息不足")
        elif actual not in {canonical(value, COUNTRY_ALIASES) for value in countries}:
            rejected.append("国家 / 地区不符合条件")
    if types:
        actual = canonical(item.company_type, TYPE_ALIASES)
        if not actual:
            pending.append("客户类型信息不足")
        elif actual not in {canonical(value, TYPE_ALIASES) for value in types}:
            rejected.append("客户类型不符合条件")
    if industries and not any(contains(text, value) for value in industries):
        pending.append("行业 / 应用场景缺少匹配依据")
    keywords = terms(keyword)
    if keywords and not any(keyword_matches(text, value) for value in keywords):
        pending.append("产品关键词缺少匹配依据")
    if external:
        pending.append("仅有搜索标题和摘要，企业身份及所在地尚未核实")
    if rejected:
        return "filtered", "；".join(rejected)
    if pending:
        return "pending_review", "；".join(pending)
    return "shortlisted", "符合已填写的筛选条件"
