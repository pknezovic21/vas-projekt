RESOURCE_TYPES = ("food", "water", "med")
RESOURCE_LABELS_EN = {"food": "food", "water": "water", "med": "medicine"}


def jid_user(jid):
    if jid is None:
        return None
    text = str(jid)
    return text.split("@", 1)[0]


def normalize_resources(resources):
    result = {}
    for key in RESOURCE_TYPES:
        result[key] = int(resources.get(key, 0))
    return result


def add_resources(a, b):
    result = normalize_resources(a)
    for key in RESOURCE_TYPES:
        result[key] += int(b.get(key, 0))
    return result


def subtract_resources(a, b):
    result = normalize_resources(a)
    for key in RESOURCE_TYPES:
        result[key] = max(0, result[key] - int(b.get(key, 0)))
    return result


def total_resources(resources):
    return sum(int(resources.get(key, 0)) for key in RESOURCE_TYPES)


def allocate_resources(available, request, capacity, priority=None):
    if priority is None:
        priority = ("med", "water", "food")
    shipment = {key: 0 for key in RESOURCE_TYPES}
    remaining = max(0, int(capacity))
    available_norm = normalize_resources(available)
    request_norm = normalize_resources(request)
    for key in priority:
        if remaining <= 0:
            break
        amount = min(available_norm[key], request_norm[key], remaining)
        shipment[key] = amount
        remaining -= amount
    return shipment


def clamp_resources(resources, max_values):
    result = normalize_resources(resources)
    max_norm = normalize_resources(max_values)
    for key in RESOURCE_TYPES:
        result[key] = min(result[key], max_norm[key])
    return result


def resource_diff(target, current):
    target_norm = normalize_resources(target)
    current_norm = normalize_resources(current)
    result = {}
    for key in RESOURCE_TYPES:
        result[key] = max(0, target_norm[key] - current_norm[key])
    return result


def resource_phrase(resources, include_zero=False):
    parts = []
    for key in RESOURCE_TYPES:
        value = int(resources.get(key, 0))
        if value == 0 and not include_zero:
            continue
        parts.append(f"{value} {RESOURCE_LABELS_EN.get(key, key)}")
    return ", ".join(parts) if parts else "nothing"
