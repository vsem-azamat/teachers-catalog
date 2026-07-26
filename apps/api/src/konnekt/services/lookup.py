"""Turning what a student typed into rows in the reference tables.

Students type slang, no diacritics, the wrong language and typos — often all
four at once: "нужен матан на чвуте", "prijimacky cvut", "mat analiza".

Two mechanisms, in order of confidence:

1. **Synonyms.** A curated list per subject, matched from the start of a word.
   A synonym of four characters or more may run into the middle of the word, so
   "матан" still finds "матаном" and "линал" finds "линала" — Russian and Czech
   inflect, and students type inflected forms. Shorter synonyms must be whole
   words, or "ос" would fire on "основы".

   What no synonym may do is start mid-word. Not
   as substrings: the synonym "TIN" sits inside "čeština", which once made
   "cestina b2 pro nostrifikaci" resolve to automata theory with full
   confidence. Both sides are reduced to space-delimited tokens and compared
   with the spaces included, so a synonym has to be whole words. A hit here is
   certain, so it scores 1.0.
2. **Trigram similarity** against every translated name, in all four languages
   at once — the person's interface language says nothing about which language
   they typed in.

`word_similarity` rather than `similarity`: the query is a sentence and the
name is two words, so plain similarity would score near zero. Word similarity
asks how well the name matches *some part* of the query, which is the actual
question.
"""

import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Below this, matches are noise. Tuned by hand against real-looking queries:
# 0.5 lets "mat analiza" reach "Matematická analýza" while keeping "fyzika"
# from reaching "Fyzikální chemie".
NAME_THRESHOLD = 0.5


def normalise(value: str) -> str:
    """Lowercase and strip Latin diacritics, the way Postgres' unaccent does.

    Only Latin. Blanket mark-stripping decomposes "й" into "и" plus a breve and
    then throws the breve away, turning "чешский" into "чешскии" — which
    Postgres does not do, so the two sides stopped agreeing and nothing matched.
    Postgres does fold "ё" to "е", so that one case is spelled out.

    This runs on Python-side text only. Anything compared inside SQL is
    normalised by SQL, so there is one implementation of the rule per
    comparison rather than two that can drift.
    """
    out: list[str] = []
    for ch in unicodedata.normalize("NFD", value.casefold()):
        # A Latin base letter loses its accent; a Cyrillic one keeps it.
        if unicodedata.combining(ch) and out and out[-1].isascii():
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out)).replace("ё", "е").strip()


# Russian speakers write Czech abbreviations in Cyrillic: "чвут", "вше",
# "муни". The mapping is Czech-flavoured rather than the usual Russian
# romanisation — ч becomes "c" (as in Č) rather than "ch", because the target
# is a Czech acronym, not an English transcription.
_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ж": "z",
        "з": "z",
        "и": "i",
        "й": "j",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "ch",
        "ц": "c",
        "ч": "c",
        "ш": "s",
        "щ": "s",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "ju",
        "я": "ja",
        "і": "i",
        "ї": "ji",
        "є": "je",
        "ґ": "g",
    }
)


def transliterate(value: str) -> str:
    """Czech-style romanisation of Cyrillic, for matching acronyms."""
    return normalise(value).translate(_TRANSLIT)


@dataclass(frozen=True)
class Match:
    id: int
    label: str
    score: float
    matched_on: str


# Reducing both sides to " token token " and comparing with the spaces kept is
# what enforces word boundaries — cheaper and less error-prone than escaping
# every synonym into a regex, and it handles multi-word synonyms unchanged.
# CAST(:p AS text) rather than :p::text — SQLAlchemy's text() refuses to treat
# a placeholder as a bind parameter when a colon follows it, so `:qnorm::text`
# reaches Postgres with the placeholder still in it.
# [[:alnum:]] rather than [a-z0-9]: the latter deletes every Cyrillic letter,
# which turned "матан" into an empty token string that matched everything.
_NORM = "immutable_unaccent(lower({expr}))"
_TOKENS = "' ' || btrim(regexp_replace({expr}, '[^[:alnum:]]+', ' ', 'g')) || ' '"

_SUBJECT_SQL = text(
    f"""
    WITH q AS (
        SELECT {_NORM.format(expr="CAST(:qnorm AS text)")} AS raw,
               {_TOKENS.format(expr=_NORM.format(expr="CAST(:qnorm AS text)"))} AS tokens
    )
    SELECT id, label, score, hit FROM (
        SELECT s.id,
               COALESCE(pref.name, any_name.name) AS label,
               (EXISTS (
                   SELECT 1 FROM unnest(s.synonyms) syn
                    WHERE btrim(syn) <> '' AND strpos(
                        q.tokens,
                        rtrim({_TOKENS.format(expr="immutable_unaccent(lower(syn))")})
                        || CASE WHEN length(btrim(syn)) >= 4 THEN '' ELSE ' ' END
                    ) > 0
               )) AS hit,
               GREATEST(
                   CASE WHEN EXISTS (
                       SELECT 1 FROM unnest(s.synonyms) syn
                        WHERE btrim(syn) <> '' AND strpos(
                            q.tokens,
                            rtrim({_TOKENS.format(expr="immutable_unaccent(lower(syn))")})
                            || CASE WHEN length(btrim(syn)) >= 4 THEN '' ELSE ' ' END
                        ) > 0
                   ) THEN 1.0 ELSE 0.0 END,
                   CASE WHEN s.external_code IS NOT NULL
                         AND strpos(
                             q.tokens,
                             {_TOKENS.format(expr="lower(s.external_code)")}
                         ) > 0
                        THEN 0.95 ELSE 0.0 END,
                   COALESCE(MAX(word_similarity(
                       immutable_unaccent(lower(i.name)), q.raw)), 0.0)
               ) AS score
          FROM subjects s
          CROSS JOIN q
          LEFT JOIN subject_i18n i ON i.subject_id = s.id
          LEFT JOIN subject_i18n pref
                 ON pref.subject_id = s.id AND pref.lang = :lang
          LEFT JOIN LATERAL (
               SELECT name FROM subject_i18n WHERE subject_id = s.id LIMIT 1
          ) any_name ON TRUE
         WHERE s.is_active AND s.kind = 'leaf'
         GROUP BY s.id, s.synonyms, s.external_code,
                  pref.name, any_name.name, q.raw, q.tokens
    ) ranked
     WHERE score >= :threshold
     ORDER BY score DESC, id
     LIMIT :limit
    """
)

_INSTITUTION_SQL = text(
    f"""
    WITH q AS (
        SELECT {_NORM.format(expr="CAST(:qnorm AS text)")} AS raw,
               {_NORM.format(expr="CAST(:qlat AS text)")} AS latin
    )
    SELECT n.id, n.label, n.score
      FROM (
        SELECT inst.id,
               COALESCE(pref.short_name, pref.name,
                        any_name.short_name, any_name.name) AS label,
               GREATEST(
                   -- The code is how people actually write it: cvut, vse, uk.
                   CASE WHEN q.raw ~ ('(^|[^a-z0-9])'
                                      || replace(inst.code, '_', '[ _-]?')
                                      || '([^a-z0-9]|$)')
                          OR q.latin ~ ('(^|[^a-z0-9])'
                                        || replace(inst.code, '_', '[ _-]?')
                                        || '([^a-z0-9]|$)')
                        THEN 1.0 ELSE 0.0 END,
                   COALESCE(MAX(word_similarity(
                       immutable_unaccent(lower(i.name)), q.raw)), 0.0),
                   COALESCE(MAX(word_similarity(
                       immutable_unaccent(lower(i.short_name)), q.raw)), 0.0),
                   COALESCE(MAX(word_similarity(
                       immutable_unaccent(lower(i.short_name)), q.latin)), 0.0)
               ) AS score
          FROM institutions inst
          CROSS JOIN q
          LEFT JOIN institution_i18n i ON i.institution_id = inst.id
          LEFT JOIN institution_i18n pref
                 ON pref.institution_id = inst.id AND pref.lang = :lang
          LEFT JOIN LATERAL (
               SELECT name, short_name FROM institution_i18n
                WHERE institution_id = inst.id LIMIT 1
          ) any_name ON TRUE
         WHERE inst.is_active
         GROUP BY inst.id, inst.code, pref.short_name, pref.name,
                  any_name.short_name, any_name.name, q.raw, q.latin
      ) n
     WHERE n.score >= :threshold
     ORDER BY n.score DESC
     LIMIT :limit
    """
)


async def find_subjects(
    session: AsyncSession,
    query: str,
    lang: str,
    *,
    limit: int = 5,
    threshold: float = NAME_THRESHOLD,
) -> list[Match]:
    rows = await session.execute(
        _SUBJECT_SQL,
        {
            "qnorm": normalise(query),
            "lang": lang,
            "limit": limit,
            "threshold": threshold,
        },
    )
    return [
        Match(
            id=r.id,
            label=r.label,
            score=float(r.score),
            matched_on="synonym" if r.hit else "name",
        )
        for r in rows
    ]


async def find_institutions(
    session: AsyncSession,
    query: str,
    lang: str,
    *,
    limit: int = 3,
    threshold: float = 0.6,
) -> list[Match]:
    rows = await session.execute(
        _INSTITUTION_SQL,
        {
            "qnorm": normalise(query),
            "qlat": transliterate(query),
            "lang": lang,
            "limit": limit,
            "threshold": threshold,
        },
    )
    return [
        Match(
            id=r.id,
            label=r.label,
            score=float(r.score),
            matched_on="code" if r.score >= 1.0 else "name",
        )
        for r in rows
    ]
