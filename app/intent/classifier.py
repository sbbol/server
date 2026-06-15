"""Классификация намерений по декларативному реестру."""

from app.intent.models import MatchedIntent, ResponseMode
from app.intent.registry import INTENT_RULES, IntentRule
from app.intent.text_utils import (
    contains_substring,
    extract_account_hint,
    fuzzy_word_match,
    is_tariff_faq_question,
    normalize,
)


_INFO_INTENT_BLOCKERS = (
    "эцп", "подпис", "ключ", "сертификат", "потеря", "утеря", "восстанов",
)

_PAYMENT_CONTEXT = (
    "плат", "плот", "перевод", "оплат", "получател", "контрагент", "сумм", "руб", "byn",
    "назначен", "мгновен", "мгвен", "поручен",
)


def _score_rule(text: str, rule: IntentRule) -> tuple[float, bool]:
    score = 0.0
    any_of_matched = False

    blockers = rule.none_of
    if rule.response_mode in (ResponseMode.DATA, ResponseMode.NAVIGATE):
        blockers = tuple(set(blockers) | set(_INFO_INTENT_BLOCKERS))
    if blockers and contains_substring(text, blockers):
        return 0.0, False

    if rule.all_of and not all(p in text for p in rule.all_of):
        return 0.0, False

    if rule.any_of and contains_substring(text, rule.any_of):
        score += 1.0
        any_of_matched = True

    if rule.fuzzy_roots and fuzzy_word_match(text, rule.fuzzy_roots):
        score += 0.8

    if rule.id == "nav_instant_payment_action":
        weak_only = contains_substring(text, ("помог", "нужно")) and not any_of_matched
        weak_only = weak_only or (
            any_of_matched
            and contains_substring(text, ("помог", "нужно"))
            and not contains_substring(text, _PAYMENT_CONTEXT)
            and not (rule.fuzzy_roots and fuzzy_word_match(text, rule.fuzzy_roots))
        )
        if weak_only:
            return 0.0, False

    # Специальный случай: номер счёта BY...
    if rule.id == "account_balance_by_number" and extract_account_hint(text):
        score += 1.2

    if rule.id == "account_balance" and extract_account_hint(text) and contains_substring(
        text, ("сколько", "скаж", "баланс", "остаток", "счет", "счете")
    ):
        score += 0.5

    # Правило без any_of/fuzzy — только all_of (например block card)
    if not rule.any_of and not rule.fuzzy_roots and rule.all_of and all(p in text for p in rule.all_of):
        score += 1.0

    if score == 0:
        return 0.0, False

    return score + rule.priority / 1000.0, any_of_matched


def classify(message: str) -> list[MatchedIntent]:
    text = normalize(message)

    if is_tariff_faq_question(message):
        return [MatchedIntent(
            intent_id="faq",
            response_mode=ResponseMode.FAQ,
            score=0.0,
        )]

    account_hint = extract_account_hint(message)

    matches: list[MatchedIntent] = []

    for rule in INTENT_RULES:
        score, any_of_matched = _score_rule(text, rule)
        if score <= 0:
            continue

        tool_args = dict(rule.tool_args or {})
        if rule.tool == "get_account_info" and account_hint:
            tool_args["account_hint"] = account_hint

        matches.append(MatchedIntent(
            intent_id=rule.id,
            response_mode=rule.response_mode,
            tool=rule.tool,
            tool_args=tool_args,
            score=score,
            guided=rule.guided,
        ))

    matches.sort(key=lambda m: m.score, reverse=True)

    seen_modes: set[ResponseMode] = set()
    deduped: list[MatchedIntent] = []
    for m in matches:
        if m.response_mode in seen_modes:
            continue
        seen_modes.add(m.response_mode)
        deduped.append(m)

    if not deduped:
        return [MatchedIntent(intent_id="faq", response_mode=ResponseMode.FAQ, score=0.0)]

    primary = deduped[0]
    if primary.score < 0.85 and primary.response_mode != ResponseMode.PERMISSION:
        return [MatchedIntent(intent_id="faq", response_mode=ResponseMode.FAQ, score=primary.score)]

    return deduped
