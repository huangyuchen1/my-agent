---
name: test
description: Testing best practices - unit tests, integration tests, TDD workflow
---

# Test Skill

## 测试金字塔

```
        /\
       /  \
      / E2E\      <- 少量，端到端
     /------\
    /Integr. \    <- 适量，服务间集成
   /----------\
  /  Unit Tests \ <- 大量，快速反馈
 /______________\
```

## 测试原则 (FIRST)

- **Fast**: 测试应该快速执行
- **Independent**: 测试之间相互独立
- **Repeatable**: 任何环境都可重复执行
- **Self-validating**: 自动判断通过/失败
- **Timely**: 与生产代码同步编写

## 单元测试结构 (AAA)

```python
def test_function_name():
    # Arrange - 准备测试数据
    input_data = "test input"
    
    # Act - 执行被测操作
    result = function_under_test(input_data)
    
    # Assert - 验证结果
    assert result == expected_value
```

## 覆盖率标准

| 场景 | 建议覆盖率 |
|------|----------|
| 核心业务逻辑 | > 80% |
| 工具函数 | > 90% |
| API Handler | > 70% |
| 简单 Getter/Setter | 可选 |

## 测试命名

```
test_<method>_<scenario>_<expected_result>

示例:
- test_user_login_success
- test_user_login_invalid_password
- test_calculate_total_with_discount
```

## Mock 策略

### 需要 Mock 的场景
- 外部 API 调用
- 数据库操作
- 文件系统操作
- 耗时操作

### 不需要 Mock 的
- 纯函数计算
- 简单数据结构
- 配置读取

### Mock 层级
```python
# 1. Mock 外部依赖
@pytest.fixture
def mock_api():
    with patch('requests.get') as mock:
        mock.return_value = Mock(json=lambda: {"data": "test"})
        yield mock

# 2. Mock 内部服务
@pytest.fixture
def mock_db():
    return Mock(get_user=Mock(return_value=test_user))

# 3. 使用 pytest-mock
def test_function(mocker):
    mock_db = mocker.patch('app.db')
    mock_db.get_user.return_value = test_user
```

## 集成测试

### 数据库测试
```python
@pytest.fixture
def test_db():
    # 使用测试数据库或事务回滚
    db = create_test_db()
    yield db
    db.destroy()
```

### API 测试
```python
def test_create_user_api(client):
    response = client.post('/api/users', json={
        'name': 'Test User',
        'email': 'test@example.com'
    })
    
    assert response.status_code == 201
    assert response.json()['email'] == 'test@example.com'
```

## TDD 流程

1. **Red**: 写一个失败的测试
2. **Green**: 写最小代码使测试通过
3. **Refactor**: 重构代码，保持测试通过

```
[写测试] -> [运行: 失败] -> [写代码] -> [运行: 通过] -> [重构] -> [重复]
```

## 常见反模式

- ❌ 测试依赖于执行顺序
- ❌ 测试之间共享可变状态
- ❌ 测试包含多个断言（难以定位失败原因）
- ❌ 使用 time.sleep 等待异步操作
- ❌ 测试私有方法（应该测试行为，不是实现）
