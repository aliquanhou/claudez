"""测试 WebSocket 交互。"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

async def test_ws():
    async with httpx.AsyncClient() as client:
        async with client.ws_connect('ws://127.0.0.1:8080/ws') as ws:
            # 发送 ping
            await ws.send_json({'action': 'ping'})
            resp = await ws.receive_json()
            print(f'Ping response: {resp}')

            # 发送消息
            await ws.send_json({'action': 'chat', 'message': 'Hello, who are you?'})
            resp = await ws.receive_json()
            print(f'Chat response type: {resp.get("type")}')
            content = resp.get("content", "")
            print(f'Content preview: {content[:300]}...')

asyncio.run(test_ws())
