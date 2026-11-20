"""Merge schema-driven profile edits without dropping fields unknown to the form."""
from copy import deepcopy


def merge_profile(original, edited, paths, protected=("personName", "#person_id", "files_path"), baseline=None):
    result = deepcopy(original)
    for path in paths:
        if not path or path[0] in protected: continue
        source = edited
        for part in path:
            if not isinstance(source, dict) or part not in source:
                source = None
                break
            source = source[part]
        if baseline is not None:
            prior = baseline
            for part in path:
                if not isinstance(prior, dict) or part not in prior:
                    prior = None
                    break
                prior = prior[part]
            if source == prior: continue
        target = result
        for part in path[:-1]:
            if not isinstance(target.get(part), dict): target[part] = {}
            target = target[part]
        if source is None: target.pop(path[-1], None)
        else: target[path[-1]] = deepcopy(source)
    return result
