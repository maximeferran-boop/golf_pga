"""Classement golf (PGA Tour par défaut) via l'API publique ESPN — sans clé.

Données non officielles : ESPN peut changer le format sans prévenir ; le code est volontairement tolérant.
"""
import json
import logging
import unicodedata
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from src.plugins.base import PluginBase, PluginResult

logger = logging.getLogger(__name__)
URL = "https://site.api.espn.com/apis/site/v2/sports/golf/{tour}/scoreboard"


def clean(text: Any, max_len: int = 22) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return text.upper().strip()[:max_len]


def score_value(s: str) -> Optional[int]:
    """'-12' -> -12, 'E' -> 0, '+3' -> 3 ; None si illisible (CUT, WD…)."""
    s = (s or "").strip().upper()
    if s in ("E", "EVEN"):
        return 0
    try:
        return int(s.replace("+", ""))
    except ValueError:
        return None


def get_score(c: Dict[str, Any]) -> str:
    sc = c.get("score")
    if isinstance(sc, dict):
        sc = sc.get("displayValue") or sc.get("value")
    return str(sc if sc is not None else "").strip()


def get_name(c: Dict[str, Any]) -> str:
    a = c.get("athlete") or {}
    last = a.get("lastName")
    if not last:
        full = a.get("displayName") or a.get("fullName") or a.get("shortName") or ""
        last = full.split()[-1] if full else "?"
    return clean(last, 30)


def get_pos(c: Dict[str, Any]) -> Optional[str]:
    st = c.get("status") or {}
    pos = (st.get("position") or {}) if isinstance(st, dict) else {}
    return pos.get("displayName") if isinstance(pos, dict) else None


class GolfPga(PluginBase):

    @property
    def plugin_id(self) -> str:
        return "golf_pga"

    def _get(self) -> Dict[str, Any]:
        tour = self.config.get("tour") or "pga"
        req = urllib.request.Request(URL.format(tour=tour), headers={"User-Agent": "FiestaBoard-golf_pga"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    @staticmethod
    def _ranking(comps: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
        """[(position, nom, score)] triés, avec égalités 'T2' calculées si ESPN ne les donne pas."""
        rows = []
        for i, c in enumerate(comps):
            sc = get_score(c)
            order = c.get("order") or c.get("sortOrder") or (i + 1)
            rows.append({"order": order, "name": get_name(c), "score": sc,
                         "val": score_value(sc), "pos": get_pos(c)})
        rows.sort(key=lambda r: (r["val"] is None, r["val"] if r["val"] is not None else 0, r["order"]))
        out = []
        for i, r in enumerate(rows):
            pos = r["pos"]
            if not pos:
                same = [x for x in rows if x["val"] is not None and x["val"] == r["val"]]
                first = next(j for j, x in enumerate(rows) if x["val"] == r["val"]) + 1
                pos = (f"T{first}" if len(same) > 1 else str(first)) if r["val"] is not None else "-"
            out.append((clean(pos, 3), r["name"], clean(r["score"], 4)))
        return out

    @staticmethod
    def _line(pos: str, name: str, score: str, cols: int) -> str:
        left = f"{pos} "
        room = cols - len(left) - len(score) - 1
        name = name[:max(room, 1)]
        return left + name + " " * (cols - len(left) - len(name) - len(score)) + score

    def fetch_data(self) -> PluginResult:
        try:
            cols = int(self.config.get("board_cols") or 15)
            raw = self._get()
            events = raw.get("events") or []
            empty = {k: "" for k in ("tournament", "round", "state", "p1_pos", "p1_name", "p1_score",
                                     "p1_line", "p2_pos", "p2_name", "p2_score", "p2_line",
                                     "p3_pos", "p3_name", "p3_score", "p3_line", "p4_line")}
            if not events:
                data = {**empty, "tournament": "PGA TOUR", "round": "PAS DE TOURNOI", "state": "AUCUN"}
                return PluginResult(available=True, data=data,
                                    formatted_lines=["PGA TOUR", "PAS DE TOURNOI", ""])
            ev = events[0]
            comp = (ev.get("competitions") or [{}])[0]
            status = comp.get("status") or ev.get("status") or {}
            stype = status.get("type") or {}
            state = stype.get("state") or ""          # pre / in / post
            period = status.get("period")
            if state == "post" or stype.get("completed"):
                round_txt = "TERMINE"
            elif state == "pre":
                round_txt = "A VENIR"
            else:
                round_txt = f"TOUR {period}" if period else "EN COURS"

            ranking = self._ranking(comp.get("competitors") or [])
            data = {**empty,
                    "tournament": clean(ev.get("shortName") or ev.get("name"), 22),
                    "round": round_txt, "state": clean(state, 10)}
            for i, (pos, name, score) in enumerate(ranking[:4], start=1):
                if i <= 3:
                    data.update({f"p{i}_pos": pos, f"p{i}_name": name[:12], f"p{i}_score": score})
                data[f"p{i}_line"] = self._line(pos, name, score, cols)

            if cols >= 22:   # Flagship 6 x 22 : tournoi, état, top 4
                lines = [data["tournament"], round_txt, data["p1_line"], data["p2_line"],
                         data["p3_line"], data["p4_line"]]
            elif state == "pre" or not ranking:
                lines = [clean(data["tournament"], cols), round_txt, ""]
            else:            # Note 3 x 15 : top 3
                lines = [data["p1_line"], data["p2_line"], data["p3_line"]]
            return PluginResult(available=True, data=data, formatted_lines=[l[:cols] for l in lines])
        except Exception as e:
            logger.exception("golf_pga: échec")
            return PluginResult(available=False, error=str(e))

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        if (config.get("tour") or "pga") not in ("pga", "eur", "lpga"):
            return ["Circuit inconnu"]
        return []
