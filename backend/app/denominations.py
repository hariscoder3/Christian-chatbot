"""Denomination awareness.

The selected tradition shapes framing, canon notes, and which authoritative
sources to reference. The assistant always presents the selected tradition's view
AND neutrally notes where major traditions diverge — it never asserts one
tradition's contested position as universal fact.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Denomination:
    id: str
    label: str
    canon: str
    distinctives: list[str]
    sources: list[str]
    framing: str


DENOMINATIONS: dict[str, Denomination] = {
    "neutral": Denomination(
        id="neutral",
        label="Ecumenical / Non-denominational",
        canon="Uses the 66-book Protestant canon for citations by default; notes that "
        "Catholic and Orthodox canons include additional (deuterocanonical) books.",
        distinctives=[
            "Present the major Christian traditions side by side on contested points.",
            "Emphasize the historic creeds (Apostles', Nicene) as common ground.",
        ],
        sources=["The Bible (KJV)", "Apostles' Creed", "Nicene Creed"],
        framing="Answer ecumenically. On doctrines where Catholics, Protestants, and "
        "Orthodox differ, summarize each view fairly and attribute it, rather than "
        "picking one as the single truth.",
    ),
    "catholic": Denomination(
        id="catholic",
        label="Roman Catholic",
        canon="73-book canon including the deuterocanonical books (e.g., Tobit, Wisdom, "
        "Sirach, 1–2 Maccabees). (Demo cites KJV text, which omits these — flag that "
        "limitation when relevant.)",
        distinctives=[
            "Sacred Tradition and Scripture together; teaching authority of the Magisterium.",
            "Seven sacraments; the Eucharist as transubstantiation; apostolic succession.",
            "Role of Mary and the saints; purgatory.",
        ],
        sources=["The Bible", "Catechism of the Catholic Church", "Ecumenical councils"],
        framing="Answer from a Roman Catholic perspective, grounded in Scripture and the "
        "Catechism. Where Protestants or Orthodox differ, note it respectfully.",
    ),
    "protestant": Denomination(
        id="protestant",
        label="Protestant (Evangelical/Reformed)",
        canon="66-book canon (matches the KJV used here).",
        distinctives=[
            "Sola Scriptura — Scripture as the final authority.",
            "Justification by grace through faith (sola fide); priesthood of all believers.",
            "Typically two ordinances (baptism, communion); wide internal diversity.",
        ],
        sources=["The Bible", "Reformation confessions (e.g., Westminster, Augsburg)"],
        framing="Answer from a Protestant perspective centered on Scripture. Acknowledge "
        "the diversity within Protestantism and note Catholic/Orthodox differences fairly.",
    ),
    "orthodox": Denomination(
        id="orthodox",
        label="Eastern Orthodox",
        canon="Includes the deuterocanonical/anagignoskomena books. (Demo cites KJV text "
        "— flag the canon difference when relevant.)",
        distinctives=[
            "Holy Tradition (Scripture, councils, Fathers, liturgy) as a unified whole.",
            "Theosis (deification); mystery (sacrament) of the Eucharist.",
            "Veneration of icons; conciliar authority rather than papal supremacy.",
        ],
        sources=["The Bible", "The Seven Ecumenical Councils", "The Church Fathers"],
        framing="Answer from an Eastern Orthodox perspective, grounded in Scripture and "
        "Holy Tradition. Note where Catholic/Protestant views differ, respectfully.",
    ),
}


def get_denomination(denom_id: str | None) -> Denomination:
    return DENOMINATIONS.get(denom_id or "neutral", DENOMINATIONS["neutral"])


def denomination_guidance(denom_id: str | None) -> str:
    d = get_denomination(denom_id)
    return "\n".join(
        [
            f"DENOMINATIONAL LENS: {d.label}",
            f"- Canon: {d.canon}",
            f"- Key distinctives: {' '.join(d.distinctives)}",
            f"- Authoritative sources to reference: {', '.join(d.sources)}.",
            f"- Framing: {d.framing}",
        ]
    )
