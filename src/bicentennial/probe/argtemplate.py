"""Fill declared recall arguments without interpreting other placeholders."""

import json

from bicentennial.canon import canon


def fill(template, prompt) -> dict:
    if type(template) is not dict:
        raise ValueError("argument template must be a dict")

    def replace(value):
        if isinstance(value, str):
            rest = value.replace("{prompt}", "")
            if "{" in rest or "}" in rest:
                raise ValueError("unsupported placeholder")
            return value.replace("{prompt}", prompt)
        if isinstance(value, dict):
            if any("{" in key or "}" in key for key in value):
                raise ValueError("brace in template key")
            return {key: replace(child) for key, child in value.items()}
        if isinstance(value, list):
            return [replace(child) for child in value]
        return value

    return json.loads(canon(replace(template)))


def recall_call(entry, query) -> dict | None:
    recall = entry["recall"]
    if recall is None:
        return None
    if recall["tool"] not in entry["read_tools"]:
        raise ValueError("recall tool is not a declared read tool")
    return {"name": recall["tool"],
            "arguments": canon(fill(recall["argument_template"], query)).decode()}
