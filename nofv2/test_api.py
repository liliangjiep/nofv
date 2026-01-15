# test_api.py - 测试 Claude API 连接
import requests
import json

# 你的配置
CLAUDE_API_KEY = "123456"
CLAUDE_MODEL = "claude-opus-4-5"
CLAUDE_URL = "http://localhost:3131/v1"

def test_connection():
    """测试 API 连接"""
    
    # 1. 测试基础连接
    print("=" * 50)
    print("1. 测试基础连接...")
    try:
        resp = requests.get(f"{CLAUDE_URL}/models", timeout=5)
        print(f"   ✅ 基础连接成功, HTTP {resp.status_code}")
        print(f"   响应: {resp.text[:200]}...")
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ 连接失败: {e}")
        print("   👉 请确认 localhost:3131 服务是否已启动")
        return
    except Exception as e:
        print(f"   ⚠️ 其他错误: {e}")
    
    # 2. 测试 chat/completions 端点
    print("\n" + "=" * 50)
    print("2. 测试 /chat/completions 端点...")
    
    url = f"{CLAUDE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {CLAUDE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": CLAUDE_MODEL,
        "messages": [{"role": "user", "content": "Hello, just testing. Reply with 'OK'."}],
        "max_tokens": 10
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"   HTTP 状态码: {resp.status_code}")
        
        if resp.status_code == 200:
            print(f"   ✅ API 调用成功!")
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"   响应内容: {content}")
        else:
            print(f"   ❌ API 调用失败")
            print(f"   响应: {resp.text[:500]}")
            
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ 连接失败: {e}")
    except Exception as e:
        print(f"   ❌ 错误: {e}")

    # 3. 检查你代码中的 URL 问题
    print("\n" + "=" * 50)
    print("3. 检查 URL 配置...")
    print(f"   你配置的 CLAUDE_URL: {CLAUDE_URL}")
    print(f"   代码实际请求的地址: {CLAUDE_URL} (直接用，没拼接 /chat/completions)")
    print(f"   正确的请求地址应该是: {CLAUDE_URL}/chat/completions")
    print("\n   👉 问题: 你的代码直接 POST 到 CLAUDE_URL，但应该 POST 到 CLAUDE_URL + '/chat/completions'")
    print("   👉 解决方案:")
    print("      方案A: 把 config.py 中的 CLAUDE_URL 改成完整路径:")
    print(f'             CLAUDE_URL = "{CLAUDE_URL}/chat/completions"')
    print("      方案B: 修改 deepseek_batch_pusher.py 中的请求代码")

if __name__ == "__main__":
    test_connection()
