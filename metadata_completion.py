"""Complete author metadata only from explicit evidence in the same source row."""

import re
import unicodedata

EVIDENCE_COLUMN = "自动补全依据"


def text(value):
    value = str(value or "").strip()
    return "" if value.casefold() in {"nan", "none", "null"} else value


def field(row, *names):
    columns = {str(k).strip().casefold(): k for k in row.keys()}
    for name in names:
        key = columns.get(name.casefold())
        if key is not None and text(row[key]):
            return text(row[key])
    return ""


def values(value):
    return [s.strip() for s in re.split(r"[;；]", text(value)) if s.strip()]


def author_parts(value):
    match = re.search(r"\s*\(([\d,，\s]+)\)\s*$", value)
    if not match:
        return value.strip(), []
    return value[:match.start()].strip(), list(dict.fromkeys(int(n) for n in re.findall(r"\d+", match[1])))


def name_key(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def initials_key(value):
    value = value.replace("，", ",")
    if "," not in value:
        # Only abbreviations with a clear surname are considered without a comma.
        tokens = re.findall(r"[^\W\d_]+", value, re.UNICODE)
        if len(tokens) < 2:
            return None
        if all(len(t) == 1 for t in tokens[:-1]):
            surname, given = tokens[-1], tokens[:-1]
        elif all(len(t) == 1 or (t.isupper() and len(t) <= 4) for t in tokens[1:]):
            surname, given = tokens[0], tokens[1:]
        else:
            return None
    else:
        surname, given_text = value.split(",", 1)
        given = re.findall(r"[^\W\d_]+", given_text, re.UNICODE)
    initials = "".join(t if t.isupper() and len(t) <= 4 else t[0] for t in given).casefold()
    return (name_key(surname), initials) if surname and initials else None


def unique_author(candidate, authors):
    """Return an index only for a unique exact or surname/initials match."""
    exact = [i for i, name in enumerate(authors) if name_key(name) == name_key(candidate)]
    if exact:
        return exact[0] if len(exact) == 1 else None
    key = initials_key(candidate)
    matches = [i for i, name in enumerate(authors) if key and initials_key(name) == key]
    return matches[0] if len(matches) == 1 else None


def numbered_affiliations(value):
    """Read EI's (n) boundaries; semicolons inside addresses are not boundaries.

    Reject conflicting duplicate identifiers or any unnumbered prefix.
    This parser must not be used to infer links from legacy untagged WOS lists.
    """
    value = text(value)
    matches = list(re.finditer(r"\((\d+)\)\s*", value))
    if not matches or value[:matches[0].start()].strip(" ;；"):
        return None
    result = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(value)
        address = value[match.end():end].strip(" ;；")
        idx = int(match[1])
        if not address or idx < 1 or (idx in result and result[idx] != address):
            return None
        result[idx] = address
    return result


def add_evidence(record, note):
    notes = [n for n in text(record.get(EVIDENCE_COLUMN)).split("；") if n]
    if note not in notes:
        notes.append(note)
    record[EVIDENCE_COLUMN] = "；".join(notes)


def complete_ei_record(record, row):
    raw_authors = field(row, "Author", "Author(s)", "Authors", "作者")
    raw_affs = field(row, "Author affiliation", "Affiliation", "作者单位", "机构")
    authors = [author_parts(a) for a in values(raw_authors)]
    units = numbered_affiliations(raw_affs)
    if units:
        # Standardize separators for the target format without discarding address text.
        units = {i: re.sub(r"\s*[;；]\s*", ", ", a) for i, a in units.items()}
        record["作者单位"] = "; ".join(f"({i}) {a}" for i, a in units.items())
        record["作者"] = "; ".join(
            name + ("(" + ",".join(map(str, ids)) + ")" if ids else "")
            for name, ids in authors
        )
        if authors:
            record["第一作者"] = authors[0][0]
            first_ids = authors[0][1]
            record["第一作者单位"] = "; ".join(units[i] for i in first_ids) if first_ids and all(i in units for i in first_ids) else ""
        add_evidence(record, "EI 作者—单位：Author 与 Author affiliation 的原始编号")
    elif raw_affs.lstrip().startswith("("):
        # An invalid catalogue must not become a confidently assigned first unit.
        record["第一作者单位"] = ""

    raw_corr = field(row, "Corresponding author(s)", "Corresponding author", "Corresponding authors", "通讯作者")
    if not raw_corr:
        return record
    candidates = [re.sub(r"\([^)]*@[^)]*\)", "", n).strip() for n in values(raw_corr)]
    candidates = [n for n in candidates if n]
    names = [name for name, _ in authors]
    resolved = [unique_author(n, names) for n in candidates]
    record["通讯作者"] = "; ".join(dict.fromkeys(names[i] if i is not None else n for n, i in zip(candidates, resolved)))
    record["通讯作者单位"] = ""
    add_evidence(record, "EI 通讯作者：Corresponding author(s) 明示姓名")
    if candidates and units and all(i is not None and authors[i][1] and all(j in units for j in authors[i][1]) for i in resolved):
        ids = list(dict.fromkeys(j for i in resolved for j in authors[i][1]))
        record["通讯作者单位"] = "; ".join(units[i] for i in ids)
        record["_ei_completed_correspondence"] = [
            {"name": names[i], "affiliations": [units[j] for j in authors[i][1]]}
            for i in dict.fromkeys(resolved)
        ]
        add_evidence(record, "EI 通讯作者单位：唯一姓名匹配及原始单位编号")
    return record


def address_key(value):
    # Ignore only typography, not institution words or the order of address parts.
    return name_key(value)


def attach_explicit_address(record, candidate, address, source):
    """Add a missing link to one uniquely identified author; keep other gaps visible."""
    address = text(address).strip(" ,;；")
    if not address or "@" in address:
        return record
    entries = [author_parts(a) for a in values(record.get("作者"))]
    index = unique_author(candidate, [n for n, _ in entries])
    if index is None or entries[index][1]:
        return record
    # Process each output item separately, preserving unlinked legacy addresses.
    items = values(record.get("作者单位"))
    numbered = {}
    for i, item in enumerate(items):
        m = re.match(r"^\((\d+)\)\s*(.+)$", item)
        if m:
            number = int(m[1])
            if number in numbered:
                return record
            numbered[number] = (i, m[2])
    references = [j for _, ids in entries for j in ids]
    next_id = max([0, *numbered, *references]) + 1
    added_ids = []
    for explicit in values(address):
        matching = [j for j, item in enumerate(items) if address_key(re.sub(r"^\(\d+\)\s*", "", item)) == address_key(explicit)]
        if len(matching) > 1:
            return record
        if matching:
            j = matching[0]
            m = re.match(r"^\((\d+)\)", items[j])
            if m:
                added_ids.append(int(m[1]))
            else:
                items[j] = f"({next_id}) {items[j]}"
                added_ids.append(next_id)
                next_id += 1
        else:
            items.append(f"({next_id}) {explicit}")
            added_ids.append(next_id)
            next_id += 1
    if not added_ids:
        return record
    entries[index] = (entries[index][0], list(dict.fromkeys(added_ids)))
    record["作者"] = "; ".join(n + (" (" + ",".join(map(str, ids)) + ")" if ids else "") for n, ids in entries)
    record["作者单位"] = "; ".join(items)
    if index == 0:
        record["第一作者单位"] = address
    add_evidence(record, f"{source}：{entries[index][0]} 的明示通讯地址补作者—单位关联")
    return record


def complete_wos_record(record, row):
    raw = field(row, "Reprint Addresses", "RP", "通讯地址")
    markers = list(re.finditer(r"\((?:corresponding|reprint) author\)", raw, flags=re.I))
    # Multiple correspondence groups need their own parser, never flatten them.
    if len(markers) != 1:
        return record
    marker = markers[0]
    candidates = values(raw[:marker.start()])
    address = raw[marker.end():].strip(" ,;；")
    for candidate in candidates:
        record = attach_explicit_address(record, candidate, address, "WOS Reprint Addresses")
    return record


def complete_scopus_record(record, row):
    raw = field(row, "Correspondence Address", "通讯地址", "通信地址", "通讯作者地址", "联系地址")
    # One direct correspondence group only; no inference from author ordering.
    segments = values(raw)
    email_positions = [i for i, s in enumerate(segments) if "@" in s or "email:" in s.casefold()]
    if not segments or len(email_positions) > 1:
        return record
    if email_positions and email_positions[0] != len(segments) - 1:
        return record
    address_segments = segments[1:email_positions[0]] if email_positions else segments[1:]
    if address_segments:
        return attach_explicit_address(record, segments[0], "; ".join(address_segments), "Scopus Correspondence Address")
    return record
