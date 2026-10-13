# -*- coding: utf-8 -*-
"""growth/audience：受众智能层——画像 / 生命周期 / AVS 评分。"""

from __future__ import annotations

import json

import pytest

from api.services.growth import audience


class TestPersonaInference:
    def test_student(self):
        assert audience.infer_persona("我目前大三第一学期，在重修刷绩点，需要复习的课有九门")[0] == "学生"

    def test_researcher(self):
        assert audience.infer_persona("科研画图，导师让投论文，图要用矢量格式")[0] == "科研人群"

    def test_creator(self):
        assert audience.infer_persona("我想做视频接单，剪辑 workflow 怎么搭")[0] == "创作者"

    def test_worker(self):
        assert audience.infer_persona("办公室周报想用AI提效，有什么工具")[0] == "职场人群"

    def test_generic_fallback(self):
        name, weight = audience.infer_persona("这个东西怎么弄的啊")
        assert name == "未识别" and 0 < weight <= 1


class TestLifecycleInference:
    def test_pay(self):
        assert audience.infer_lifecycle("这个会员多少钱一个月，值不值") == "付费"

    def test_deep(self):
        assert audience.infer_lifecycle("两个模型的工作流参数对比，一致性怎么调") == "深入"

    def test_try(self):
        assert audience.infer_lifecycle("零基础怎么入门做AI视频") == "尝试"

    def test_awareness(self):
        assert audience.infer_lifecycle("AI到底是什么，真的能代替人吗") == "认知"


class TestAnalyzeComments:
    def _rows(self):
        return [
            {"comment_id": "1", "content": "求提示词分享一下，谢谢", "like_count": 3, "video_id": "v1"},
            {"comment_id": "2", "content": "大三学生想用AI辅助复习，求教程", "like_count": 1, "video_id": "v1"},
            {"comment_id": "3", "content": "怎么才能用上gpt啊，注册不了", "like_count": 2, "video_id": "v2"},
            {"comment_id": "4", "content": "怎么才能用上claude，哪里买账号", "like_count": 5, "video_id": "v2"},
            {"comment_id": "5", "content": "本地部署comfyui工作流的参数怎么调", "like_count": 0, "video_id": "v3"},
        ]

    def test_clusters_and_verdicts(self):
        video_map = {"v1": {"video_play_count": 50000}, "v2": {"video_play_count": 90000}, "v3": {"video_play_count": 1000}}
        report = audience.analyze_comments(self._rows(), video_map)
        by_cluster = {c["cluster"]: c for c in report["clusters"]}
        # 使用渠道：需求 2 条但 M=0 → 必须 REJECT（用户的高需求低配示例）
        ch = by_cluster["使用渠道_账号"]
        assert ch["verdict"] == "reject"
        assert ch["avs"]["match"] == 0.0
        # 求做法资产 M=0.9 → 不应是 reject
        assert by_cluster["提示词_求做法资产"]["verdict"] != "reject"

    def test_persona_and_lifecycle_dist(self):
        report = audience.analyze_comments(self._rows(), {})
        by_cluster = {c["cluster"]: c for c in report["clusters"]}
        res = by_cluster["提示词_求做法资产"]
        assert "学生" in res["persona_dist"]
        assert res["lifecycle_dist"].get("尝试", 0) >= 1

    def test_pay_intent_ratio(self):
        report = audience.analyze_comments(self._rows(), {})
        by_cluster = {c["cluster"]: c for c in report["clusters"]}
        assert by_cluster["使用渠道_账号"]["pay_intent_ratio"] == 0.5  # 买账号 有付费意图

    def test_results_sorted_by_avs(self):
        video_map = {"v1": {"video_play_count": 50000}, "v2": {"video_play_count": 90000}}
        report = audience.analyze_comments(self._rows(), video_map)
        scores = [c["avs"]["score"] for c in report["clusters"]]
        assert scores == sorted(scores, reverse=True)


class TestSyncIdempotent:
    def test_double_sync_no_duplicate_signals(self, tmp_path, monkeypatch):
        # 用临时产品目录跑两遍 sync，signal 只加一次、opportunity upsert 幂等
        # 注意：必须 patch GROWTH_ROOT（模块级常量，导入时从 DATA_DIR 派生），
        # patch DATA_DIR 无效——曾导致测试数据写进正式目录
        from api.services.growth import store as gstore
        from api.services.growth.models import ProductProfile

        monkeypatch.setattr(gstore, "GROWTH_ROOT", tmp_path, raising=True)
        gstore.upsert_product(ProductProfile(product_id="test_prod", name="测试产品"))
        video_map = {"v1": {"video_play_count": 5000}}
        rows = [
            {"comment_id": "1", "content": "求提示词分享，做同款", "like_count": 2, "video_id": "v1"},
        ]
        report = audience.analyze_comments(rows, video_map)
        s1 = audience.sync_to_engine(report, "test_prod", dataset_ref="t")
        s2 = audience.sync_to_engine(report, "test_prod", dataset_ref="t")
        assert s1["signals_added"] >= 1
        assert s2["signals_added"] == 0  # 幂等
        opps = gstore.list_opportunities("test_prod")
        assert len(opps) == len(report["clusters"])


class TestTopicLifecycle:
    def test_lifecycle_field_present(self):
        video_map = {"v1": {"video_play_count": 5000}}
        rows = [
            {"comment_id": "1", "content": "求提示词分享做同款", "like_count": 2, "video_id": "v1"},
            {"comment_id": "2", "content": "gpt6和claude哪个好怎么选", "like_count": 1, "video_id": "v1"},
        ]
        report = audience.analyze_comments(rows, video_map)
        valid = {"hot", "seasonal", "evergreen", "decay"}
        for c in report["clusters"]:
            assert c["topic_lifecycle"] in valid and c["lifecycle_play"]
        by = {c["cluster"]: c for c in report["clusters"]}
        assert by["提示词_求做法资产"]["topic_lifecycle"] == "evergreen"
        assert by["模型选择_横评"]["topic_lifecycle"] == "hot"

    def test_opportunity_carries_lifecycle(self, tmp_path, monkeypatch):
        from api.services.growth import store as gstore
        from api.services.growth.models import ProductProfile

        monkeypatch.setattr(gstore, "GROWTH_ROOT", tmp_path, raising=True)
        gstore.upsert_product(ProductProfile(product_id="p1", name="t"))
        report = audience.analyze_comments(
            [{"comment_id": "1", "content": "求提示词分享做同款", "like_count": 2, "video_id": "v1"}],
            {"v1": {"video_play_count": 5000}},
        )
        audience.sync_to_engine(report, "p1")
        opps = gstore.list_opportunities("p1")
        assert any("选题生命周期" in o.production_need for o in opps)


class TestMultiDirAndRefresh:
    def _mk(self, d, cid, content="求提示词分享一下，谢谢"):
        d.mkdir(parents=True, exist_ok=True)
        with (d / "comments_x.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"comment_id": cid, "content": content, "like_count": 1, "video_id": "v1"}) + "\n")
        p = d / "contents_x.jsonl"
        if not p.exists():
            p.write_text(
                json.dumps({"video_id": "v1", "title": "新手教程", "video_play_count": 1000}) + "\n",
                encoding="utf-8",
            )

    def test_multi_dir_merge_dedup(self, tmp_path):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        self._mk(d1, "c1")
        self._mk(d2, "c1")  # 同一条评论在两个目录（多轮采集）
        self._mk(d2, "c2", "怎么入门做ai视频新手")
        rows, video_map, ref = audience.load_bili_comments([d1, d2])
        assert len(rows) == 3  # 原始行
        report = audience.analyze_comments(rows, video_map)
        total = sum(c["demand_count"] for c in report["clusters"])
        assert total == 2  # comment_id 去重后

    def test_refresh_default(self, tmp_path, monkeypatch):
        from api.services.growth import store as gstore
        from api.services.growth.models import ProductProfile

        monkeypatch.setattr(gstore, "GROWTH_ROOT", tmp_path / "store", raising=True)
        gstore.upsert_product(ProductProfile(product_id="p1", name="t"))
        self._mk(tmp_path / "data1", "c1")
        res = audience.refresh_default(product_id="p1", data_dirs=[tmp_path / "data1"])
        assert res["ok"] is True and res["clusters"] >= 1
        assert res["top"][0]["lifecycle"] in {"hot", "seasonal", "evergreen", "decay"}
