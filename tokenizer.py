from janome.tokenizer import Tokenizer

from dict_engine import dict_engine

_tokenizer = Tokenizer()

ALLOWED_POS = {"名詞", "動詞", "形容詞", "副詞", "連体詞", "感動詞"}


def analyze(text: str) -> list[dict]:
    if not text:
        return []

    results: list[dict] = []
    seen_bases: set[str] = set()

    for token in _tokenizer.tokenize(text):
        pos_details = token.part_of_speech.split(",")
        if pos_details[0] not in ALLOWED_POS:
            continue

        base_form = token.base_form
        if base_form in seen_bases:
            continue
        seen_bases.add(base_form)

        dict_data = dict_engine.lookup(base_form)
        reading = dict_data["r"] or token.reading

        results.append({
            "s": token.surface,
            "b": base_form,
            "p": pos_details[0],
            "r": reading,
            "d": dict_data["d"],
        })

    return results
