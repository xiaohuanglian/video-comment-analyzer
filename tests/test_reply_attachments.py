import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from api.routers import automation
from api.services.outreach import reply_attachments as images
from api.services.outreach import reply_automation as auto
from api.services.outreach import reply_sender


def png():
    stream = io.BytesIO()
    Image.new('RGB', (4, 5), color='white').save(stream, format='PNG')
    return stream.getvalue()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(images, 'ROOT', tmp_path / 'images')
    store = auto.AutomationStore(tmp_path / 'store.json')
    store.add_items([{'id': 'one', 'comment_id': '1', 'status': 'pending_review', 'draft': '具体回复', 'profile_id': '产品', 'attachments': []},
                     {'id': 'other', 'comment_id': '2', 'status': 'pending_review', 'draft': '另一回复'}])
    monkeypatch.setattr(automation, '_store', lambda *args: store)
    app = FastAPI()
    app.include_router(automation.router)
    return store, TestClient(app)


def test_upload_preview_scope_and_remove_without_platform_write(setup, monkeypatch):
    store, client = setup
    def should_not_send(*args, **kwargs):
        raise AssertionError('添加/预览附件不应调用平台')
    monkeypatch.setattr(reply_sender.httpx, 'Client', should_not_send)
    result = client.post('/automation/candidates/one/attachments?filename=照片.png', content=png())
    assert result.status_code == 200
    metadata = result.json()['item']['attachments'][0]
    identity = metadata['attachment_id']
    preview = client.get(f'/automation/candidates/one/attachments/{identity}')
    assert preview.content == png()
    assert preview.headers['content-type'] == 'image/png'
    assert client.get(f'/automation/candidates/other/attachments/{identity}').status_code == 404
    assert client.delete(f'/automation/candidates/one/attachments/{identity}').status_code == 200
    assert store.find('one')['attachments'] == []


def test_uploaded_attachment_is_immutable_after_approval(setup):
    store, client = setup
    identity = client.post('/automation/candidates/one/attachments', content=png()).json()['item']['attachments'][0]['attachment_id']
    store.find('one')['status'] = 'approved'
    assert client.delete(f'/automation/candidates/one/attachments/{identity}').status_code == 400
    assert client.post('/automation/candidates/one/attachments', content=png()).status_code == 400


def test_bad_images_and_traversal_are_rejected(setup):
    _, client = setup
    assert client.post('/automation/candidates/one/attachments', content=b'<svg><script/></svg>').status_code == 400
    with pytest.raises(ValueError):
        images.image_path({'attachment_id': '../credentials', 'extension': 'png'})
    with pytest.raises(ValueError):
        images.inspect_image(b'x' * (images.MAX_BYTES + 1))


def test_browser_platform_does_not_approve_or_drop_images(setup):
    store, client = setup
    client.post('/automation/candidates/one/attachments', content=png())
    store.platform = 'xhs'
    with pytest.raises(ValueError, match='不会忽略图片'):
        store.decide('one', 'approve')
    assert store.find('one')['status'] == 'pending_review'


def test_bilibili_sends_uploaded_image_metadata_with_comment(setup, monkeypatch):
    _, client = setup
    metadata = client.post('/automation/candidates/one/attachments', content=png()).json()['item']['attachments'][0]
    calls = []
    class Response:
        def __init__(self, payload): self.payload = payload
        def json(self): return self.payload
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            if 'upload_bfs' in url:
                return Response({'code': 0, 'data': {'image_url': 'https://i0.hdslb.com/example.png', 'image_width': 4, 'image_height': 5, 'img_size': 1}})
            return Response({'code': 0, 'data': {'rpid': 'new-reply'}})
    monkeypatch.setattr(reply_sender.httpx, 'Client', FakeClient)
    reply = reply_sender.send_bilibili_reply(content_id='123', comment_id='456', message='正文', cookie='bili_jct=token;', attachments=[metadata])
    assert reply == 'new-reply'
    assert len(calls) == 2
    assert calls[0][1]['files']['file_up'][1] == png()
    payload = calls[1][1]['data']
    assert payload['root'] == '456'
    assert payload['message'] == '正文'
    assert json.loads(payload['pictures'])[0]['img_src'] == 'https://i0.hdslb.com/example.png'


def test_missing_image_never_falls_back_to_text_only(setup, monkeypatch):
    _, client = setup
    metadata = client.post('/automation/candidates/one/attachments', content=png()).json()['item']['attachments'][0]
    images.image_path(metadata).unlink()
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): calls.append(args)
    monkeypatch.setattr(reply_sender.httpx, 'Client', FakeClient)
    with pytest.raises(ValueError, match="图片附件不存在"):
        reply_sender.send_bilibili_reply(content_id='123', comment_id='456', message='正文', cookie='bili_jct=token;', attachments=[metadata])
    assert not calls


def test_sender_never_silently_drops_unsupported_platform_images(setup):
    import asyncio
    store, client = setup
    client.post('/automation/candidates/one/attachments', content=png())
    item = store.find('one')
    item['status'] = 'approved'
    calls = []
    adapter = auto.PlatformSendAdapter(name='小红书', violations=lambda text: [], precondition=None, send=lambda **kwargs: calls.append(kwargs))
    message = asyncio.run(auto._run_sender_tick(store, item, adapter))
    assert not calls
    assert item['status'] == 'pending_review'
    assert '带图条目退回待审' in message
