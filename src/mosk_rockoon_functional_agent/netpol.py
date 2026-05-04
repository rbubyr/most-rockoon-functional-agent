"""NetworkPolicy helpers for Rockoon exporter ingress ipBlock."""

from __future__ import annotations

import json
from typing import Any


def list_exporter_candidate_netpols(
    doc: dict[str, Any],
    *,
    name_keyword: str = "exporter",
) -> list[dict[str, Any]]:
    """
    Return NetworkPolicy items whose **metadata.name** contains ``name_keyword`` (case-insensitive).

    Operators usually identify the functional-test exporter policy with:

    ``kubectl -n osh-system get networkpolicy`` and look for **exporter** in the **NAME** column
    (e.g. ``rockoon-exporter-netpol-openstack``). Other releases may use names such as
    ``openstack-controller-exporter-netpol-openstack``; the same **exporter** substring matches both.
    """
    kw = (name_keyword or "exporter").lower()
    out: list[dict[str, Any]] = []
    for item in doc.get("items") or []:
        meta = item.get("metadata") or {}
        name = (meta.get("name") or "").lower()
        if not name or kw not in name:
            continue
        spec = item.get("spec") or {}
        pod_sel = spec.get("podSelector") or {}
        match_labels = pod_sel.get("matchLabels") or {}
        out.append(
            {
                "name": meta.get("name"),
                "namespace": meta.get("namespace"),
                "labels": meta.get("labels"),
                "pod_selector_match_labels": match_labels,
            }
        )
    return out


def ingress_from_has_cidr(spec: dict[str, Any], cidr: str) -> bool:
    for rule in spec.get("ingress") or []:
        for ent in rule.get("from") or []:
            ib = ent.get("ipBlock") or {}
            if ib.get("cidr") == cidr:
                return True
    return False


def first_ingress_from_path(spec: dict[str, Any]) -> str | None:
    ing = spec.get("ingress") or []
    if not ing:
        return None
    if "from" not in ing[0]:
        return None
    return "/spec/ingress/0/from"


def build_add_ipblock_patch(cidr: str) -> list[dict[str, Any]]:
    return [{"op": "add", "path": "/spec/ingress/0/from/-", "value": {"ipBlock": {"cidr": cidr}}}]


def summarize_netpol_for_tool(stdout: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON from kubectl: {e}"
    return doc, None
