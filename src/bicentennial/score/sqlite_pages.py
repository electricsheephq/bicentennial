"""Pre-recovery SQLite page images and linked whole-token evidence.

This is a byte-evidence scan, not recovery: salts, checksums and commit markers
must not discard superseded images. All paths supplied here are private copies.
"""

from collections import defaultdict

JOURNAL_MAGIC = bytes.fromhex("d9d505f920a163d7")


def _uint(data, offset=0):
    return int.from_bytes(data[offset:offset + 4], "big")


def _page_size(size):
    return 512 <= size <= 65536 and not size & (size - 1)


def _page_number(number):
    return 0 < number < 0xffffffff


def _wal(data):
    if (len(data) < 32 or _uint(data) not in (0x377f0682, 0x377f0683)
            or _uint(data, 4) != 3007000):
        return []
    size = _uint(data, 8)
    if not _page_size(size):
        return []
    # A partially written trailing frame has no complete page image, and a frame
    # without a valid page number (a zeroed hole) has none either. The other
    # complete frames, including old generations past the current end, remain.
    pages = []
    for offset in range(32, len(data) - size - 23, size + 24):
        number = _uint(data, offset)
        if _page_number(number):
            pages.append((number, data[offset + 24:offset + 24 + size]))
    return pages


def _journal(data, database_size):
    if len(data) < 28:
        return []
    sector, size = _uint(data, 20), _uint(data, 24)
    erased = not any(data[:28])
    if erased:
        # PERSIST zeros the entire header, including both sizes. Its sector
        # padding survives. Try the supported power-of-two sector geometries;
        # only a layout with page records immediately after zero padding fits.
        size = database_size
        sectors = [1 << power for power in range(5, 17)]
    else:
        if data[:8] not in (JOURNAL_MAGIC, bytes(8)):
            return []
        sectors = [sector]
    if not _page_size(size):
        return []
    pages = []
    for sector in sectors:
        if (sector < 32 or sector > 65536 or sector & (sector - 1)
                or len(data) < sector + size + 8 or any(data[28:sector])):
            continue
        records, offset = [], sector
        while offset + size + 8 <= len(data):
            number = _uint(data, offset)
            if not _page_number(number) or data[offset:offset + 8] == JOURNAL_MAGIC:
                # Multiple journal segments have a new sector-aligned header.
                header = (offset + sector - 1) // sector * sector
                if (data[header:header + 8] not in (JOURNAL_MAGIC, bytes(8))
                        or _uint(data, header + 20) != sector
                        or _uint(data, header + 24) != size):
                    break
                offset = header + sector
                continue
            records.append((number, data[offset + 4:offset + 4 + size]))
            offset += size + 8
        # Counts and checksums describe recovery, not the retained evidence:
        # PERSIST may leave records from a longer previous transaction too.
        pages.extend(records)
    return pages


def page_versions(copy):
    """Collect complete images by page number, retaining their file locations."""
    data = copy.read_bytes()
    if len(data) < 100 or data[:16] != b"SQLite format 3\0":
        raise ValueError("missing SQLite page geometry")
    size = int.from_bytes(data[16:18], "big")
    size = 65536 if size == 1 else size
    usable = size - data[20]
    if not _page_size(size) or usable < 480:
        raise ValueError("invalid SQLite page geometry")
    versions = defaultdict(list)

    def add(name, pages):
        for number, page in pages:
            if len(page) == size:
                versions[number].append((name, page[:usable]))

    # An incomplete last page (a torn write) has no image; the complete pages count.
    add(copy.name, ((offset // size + 1, data[offset:offset + size])
                    for offset in range(0, len(data), size)))
    for suffix, parse in (("-wal", _wal), ("-journal", lambda d: _journal(d, size))):
        path = copy.with_name(copy.name + suffix)
        if path.exists():
            add(path.name, parse(path.read_bytes()))
    if not versions:
        raise ValueError("no SQLite page images")
    return versions


def linked_hits(copy, needles):
    """Find all byte splits, following only the encoded page-number links.

    A continuation consumes an entire usable overflow payload before following
    its next link. The needle bounds traversal; there is no page-count cap and
    no recursion, even for long needles or corrupt cyclic links.
    """
    versions = page_versions(copy)
    hits = set()
    for needle in needles:
        cache = {}

        def continues(number, start, needle=needle, cache=cache):
            initial = number, start
            pending = [(number, start)]
            seen = set()
            while pending:
                key = number, start = pending.pop()
                if key in seen:
                    continue
                seen.add(key)
                if key in cache:
                    if cache[key]:
                        return True
                    continue
                for _, page in versions.get(number, ()):
                    amount = min(len(needle) - start, len(page) - 4)
                    if page[4:4 + amount] != needle[start:start + amount]:
                        continue
                    if start + amount == len(needle):
                        cache[key] = True
                        return True
                    pending.append((_uint(page), start + amount))
            cache[initial] = False
            return False

        for pages in versions.values():
            for name, page in pages:
                for split in range(1, len(needle)):
                    prefix = needle[:split]
                    # Local payload can end anywhere within usable content.
                    offset = page.find(prefix)
                    while offset >= 0:
                        end = offset + split
                        if end + 4 <= len(page) and continues(_uint(page, end), split):
                            hits.add(name)
                            break
                        offset = page.find(prefix, offset + 1)
                    # Overflow payload ends at usable size, before reserved bytes.
                    if split <= len(page) - 4 and page.endswith(prefix) and continues(_uint(page), split):
                        hits.add(name)
    return hits
