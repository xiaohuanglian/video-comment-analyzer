import asyncio
import json

from api.services.insight.evidence_adapter import analysis_dict_from_result_row, infer_single_video_relation, outreach_analysis_from_card
from api.services.insight.evidence_schemas import EvidenceCard
from api.services.insight.statistics import build_statistics, compute_candidate_score
from api.services.outreach import reply_automation as auto


def card(expression='help_request'):
    return EvidenceCard.model_validate({'record_id': '1', 'record_status': 'usable', 'primary_expression': expression, 'evidence_level': 'strong',
        'evidence_items': [{'type': 'problem', 'text': '某个问题', 'evidence_quote': '这个问题怎么解决', 'speaker_scope': 'self', 'certainty': 'high'}]})


def test_strong_evidence_never_means_product_fit():
    result = outreach_analysis_from_card(card())
    assert result['product_fit'] == 'unclear'
    assert result['product_fit_source'] == 'not_assessed'
    legacy = analysis_dict_from_result_row({'analysis': {'product_fit': 'high', 'single_video_relation': 'one_reply_sufficient'}})
    assert legacy['product_fit'] == 'unclear'
    assert legacy['single_video_relation'] == 'unclear'


def test_help_or_simple_question_does_not_predict_answer_sufficiency():
    assert infer_single_video_relation(card()) == 'unclear'
    assert infer_single_video_relation(card('question')) == 'unclear'


def test_difficulty_and_fit_do_not_add_research_score():
    baseline = {'specific_problems': ['具体困难'], 'help_seeking': True}
    assert compute_candidate_score(baseline) == compute_candidate_score({**baseline, 'product_fit': 'high', 'single_video_relation': 'personalized_judgment_needed'})


def test_signal_coverage_counts_each_comment_once():
    summary = build_statistics([{'record_id': '1', 'analysis': {'signals': ['howto_uncertainty', 'howto_uncertainty']}}])
    assert summary['signal_coverage']['howto_uncertainty'] == {'count': 1, 'coverage_pct': 100.0}
    assert summary['projection_policy_version'] == 2


def test_reply_product_matching_requires_verbatim_need_and_real_offering():
    campaign = {'profile_id': '造浪', 'profile_name': 'YouVibe', 'reply_goal': '了解相关功能', 'reply_mode': 'recommend',
                'profile_snapshot': {'domain': 'AI内容社区', 'target_audience': 'AI爱好者', 'product_offerings': [{'name': '浏览AI作品'}]}}
    async def fake(messages, **kwargs):
        return json.dumps({'lane': 'help', 'worth': 9, 'persona': 'novice_doer', 'need_quote': '模型编的需求', 'matched_offering': '浏览AI作品', 'reason': '看起来相关'})
    kept, _ = asyncio.run(auto.llm_screen_candidates([{'comment_text': '不知道先看什么', 'video_title': 'AI作品'}], complete_fn=fake, campaign=campaign))
    assert not kept


def test_unavailable_model_does_not_claim_product_match(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise auto.LlmScreenUnavailable('offline')
    monkeypatch.setattr(auto, 'llm_screen_candidates', unavailable)
    items, stats = asyncio.run(auto._refine_candidates([{'comment_text': '想了解', 'signal': '疑问'}], {'_campaign': {'profile_id': '造浪'}}, 1))
    assert items == []
    assert stats['mode'] == 'unavailable'


def test_price_question_does_not_fabricate_usage_or_unmet_service_need():
    from api.services.insight.candidates import build_contact_reason
    reason = build_contact_reason({'specific_problems': ['询价']}, 2)
    assert '明确实际使用过' not in reason
    assert '单向内容难以解决' not in reason
    assert '不能证明实际购买' in reason


def test_semantic_recall_does_not_require_domain_words_or_question_form():
    from datetime import datetime
    texts = ['哪里找', '就是想先看看成品', '想看看你的具体操作', '这段演示让我想到我们的需求', '为什么最后一步报错了']
    rows = [{'comment_id': str(i), 'video_id': str(i), 'content': text, 'nickname': '免费分享', 'create_time': int(datetime.now().timestamp())} for i, text in enumerate(texts)]
    picked, funnel = auto.build_candidates(rows, {}, {'_semantic_recall': True, 'max_new_candidates_per_cycle': 10}, set())
    assert {item['comment_text'] for item in picked} == set(texts)
    assert funnel['excluded'] == 0


def test_semantic_recall_still_obeys_time_and_prior_contact():
    from datetime import datetime, timedelta
    now = datetime.now()
    rows = [{'comment_id': cid, 'video_id': cid, 'content': '想看看', 'create_time': int((now - timedelta(hours=age)).timestamp())} for cid, age in [('old', 200), ('seen', 1), ('new', 1)]]
    picked, funnel = auto.build_candidates(rows, {}, {'_semantic_recall': True}, {'seen'}, now=now)
    assert [item['comment_id'] for item in picked] == ['new']
    assert funnel['stale'] == 1
    assert funnel['dedup'] == 1


def test_product_task_never_falls_back_to_word_rules_when_model_disabled():
    picked, stats = asyncio.run(auto._refine_candidates([{'comment_text': '哪里找'}], {'llm_screen': False, '_campaign': {'profile_id': '造浪'}}, 1))
    assert not picked
    assert stats['mode'] == 'unavailable'
