from collections.abc import Sequence


def find_channel_edges(samples: Sequence[int], channel: int) -> list[tuple[int, bool]]:
    if not 0 <= channel < 8:
        raise ValueError("Channel index must be between 0 and 7")

    bit_mask = 1 << channel
    edges = []
    previous = samples[0] & bit_mask if samples else 0

    for sample_index in range(1, len(samples)):
        current = samples[sample_index] & bit_mask
        if current != previous:
            edges.append((sample_index, bool(current)))
        previous = current

    return edges


def format_time(seconds: float) -> str:
    absolute_seconds = abs(seconds)
    if absolute_seconds < 1e-6:
        return f"{seconds * 1e9:.4g} ns"
    if absolute_seconds < 1e-3:
        return f"{seconds * 1e6:.4g} us"
    if absolute_seconds < 1:
        return f"{seconds * 1e3:.4g} ms"
    return f"{seconds:.4g} s"
