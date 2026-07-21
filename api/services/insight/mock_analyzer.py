# -*- coding: utf-8 -*-
"""Rule-based mock analyzer for checkpoint 1 (no paid API)."""

from __future__ import annotations

import re

from .schemas import (
    CommentAnalysisResult,
    HypothesisRelation,
    HypothesisRelationType,
    NewSignal,
    NewSignalType,
    PrimaryIntent,
    ProductFit,
    SingleVideoRelation,
    SourceRecord,
    TrainingEvidence,
    TrainingImpact,
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def analyze_record_mock(record: SourceRecord) -> CommentAnalysisResult:
    text = record.comment_text.strip()
    signals: list[str] = []
    specific_problems: list[str] = []
    new_signals: list[NewSignal] = []
    hypothesis_relations: list[HypothesisRelation] = []
    evidence_quotes: list[str] = []

    def add_quote(quote: str) -> None:
        if quote and quote in text and quote not in evidence_quotes:
            evidence_quotes.append(quote)

    primary_intent = PrimaryIntent.OTHER_VALID
    actual_training = TrainingEvidence.NONE
    single_video = SingleVideoRelation.UNCLEAR
    product_fit = ProductFit.UNCLEAR
    product_fit_reason = ""
    training_impact = TrainingImpact.NONE
    help_seeking = False
    confidence = 0.78

    if text in {"已打卡。", "已打卡", "打卡"} or _contains_any(text, ("已打卡", "打卡完成")):
        primary_intent = PrimaryIntent.CHECK_IN
        signals.append("started_training")
        actual_training = TrainingEvidence.TRIED
        confidence = 0.86
    elif _contains_any(text, ("谢谢", "感谢", "认可")) and _contains_any(text, ("?", "？", "吗", "怎么", "正常吗", "为什么")):
        primary_intent = PrimaryIntent.QUESTION
        signals.extend(["gratitude", "continued_training", "asks_coach_reply"])
        if _contains_any(text, ("酸", "没感觉", "没发力", "不舒服")):
            signals.append("no_target_muscle_sensation")
            specific_problems.append("训练时出现局部发力或体感异常")
        actual_training = TrainingEvidence.CONTINUED
        single_video = SingleVideoRelation.REALTIME
        hypothesis_relations.append(
            HypothesisRelation(
                hypothesis_id="H2",
                relation=HypothesisRelationType.SUPPORTS,
                evidence_quote=text[:40],
            )
        )
        product_fit = ProductFit.HIGH
        product_fit_reason = "问题与动作质量反馈较相关"
        help_seeking = True
        add_quote(text[:40])
    elif _contains_any(text, ("一周练几次", "练几次", "多少次")):
        primary_intent = PrimaryIntent.QUESTION
        signals.append("applicability_question")
        single_video = SingleVideoRelation.ONE_REPLY
        hypothesis_relations.append(
            HypothesisRelation(hypothesis_id="H2", relation=HypothesisRelationType.INSUFFICIENT, evidence_quote=text)
        )
        confidence = 0.84
        add_quote(text)
    elif _contains_any(text, ("看不懂", "左右", "左腿", "右腿", "镜像", "同侧", "反侧")):
        primary_intent = PrimaryIntent.DIFFICULTY
        signals.append("instruction_unclear")
        single_video = SingleVideoRelation.ONE_REPLY
        new_signals.append(
            NewSignal(
                type=NewSignalType.NEW_BARRIER,
                text="跟练视频镜像方向导致左右侧别理解困难",
                evidence_quote=text[:48],
            )
        )
        help_seeking = True
        product_fit = ProductFit.MEDIUM
        product_fit_reason = "说明类问题可通过更清晰指引缓解"
        add_quote(text[:48])
    elif _contains_any(text, ("膝盖", "受伤", "损伤", "可不可以练")):
        primary_intent = PrimaryIntent.QUESTION
        signals.extend(["applicability_question", "injury_or_special_condition", "asks_coach_reply"])
        single_video = SingleVideoRelation.PERSONALIZED
        hypothesis_relations.append(
            HypothesisRelation(hypothesis_id="H1", relation=HypothesisRelationType.IRRELEVANT, evidence_quote="")
        )
        hypothesis_relations.append(
            HypothesisRelation(hypothesis_id="H2", relation=HypothesisRelationType.INSUFFICIENT, evidence_quote=text[:40])
        )
        help_seeking = True
        product_fit = ProductFit.LOW
        product_fit_reason = "涉及个体身体情况，需个性化判断"
        add_quote(text[:40])
    elif _contains_any(text, ("第二遍", "看第二遍", "就会了", "讲得很清楚")):
        primary_intent = PrimaryIntent.RESULT_FEEDBACK
        signals.append("positive_result")
        single_video = SingleVideoRelation.VIDEO_SUFFICIENT
        hypothesis_relations.append(
            HypothesisRelation(hypothesis_id="H2", relation=HypothesisRelationType.WEAKENS, evidence_quote=text[:40])
        )
        add_quote(text[:40])
    elif _contains_any(text, ("?", "？", "吗", "怎么", "为什么", "如何")):
        primary_intent = PrimaryIntent.QUESTION
        signals.append("applicability_question")
        help_seeking = True
        single_video = SingleVideoRelation.ONE_REPLY
    elif _contains_any(text, ("谢谢", "感谢", "收藏", "有用")):
        primary_intent = PrimaryIntent.GRATITUDE
        signals.append("gratitude")
    elif len(text) <= 2:
        primary_intent = PrimaryIntent.INVALID
        confidence = 0.55
    else:
        if _contains_any(text, ("练", "训练", "跟练", "打卡")):
            actual_training = TrainingEvidence.TRIED
        if _contains_any(text, ("难", "不会", "做不到", "求助", "怎么办")):
            primary_intent = PrimaryIntent.DIFFICULTY
            help_seeking = True
            signals.append("cannot_complete")

    if not hypothesis_relations:
        for hypothesis_id in ("H1", "H2", "H3"):
            hypothesis_relations.append(
                HypothesisRelation(
                    hypothesis_id=hypothesis_id,
                    relation=HypothesisRelationType.IRRELEVANT,
                    evidence_quote="",
                )
            )

    return CommentAnalysisResult(
        record_id=record.internal_record_id,
        primary_intent=primary_intent,
        signals=signals,
        specific_problems=specific_problems,
        actual_training_evidence=actual_training,
        help_seeking=help_seeking,
        training_impact=training_impact,
        single_video_relation=single_video,
        hypothesis_relations=hypothesis_relations,
        new_signals=new_signals,
        product_fit=product_fit,
        product_fit_reason=product_fit_reason[:40],
        evidence_quotes=evidence_quotes or ([text[:40]] if text else []),
        confidence=confidence,
    )
