# Kimi API 错误码参考指南

本文档整理自 [Kimi API 错误说明](https://platform.kimi.com/docs/api/errors)，帮助开发者快速定位和解决 API 调用中遇到的问题。

## 错误码总览

| HTTP 状态码 | 错误类型 | 说明 |
|------------|---------|------|
| 400 | 请求错误 | 请求格式错误、参数缺失、Token 超限等 |
| 401 | 认证错误 | API Key 无效或缺失 |
| 403 | 权限错误 | API 未开放或越权访问 |
| 404 | 资源不存在 | 模型不存在或无权限访问 |
| 429 | 限流/额度不足 | 请求过于频繁或账户余额不足 |
| 500 | 服务端错误 | Kimi 服务器内部问题 |

---

## 400 - 请求错误 (Request Error)

### content_filter

**错误信息**: `The request was rejected because it was considered high risk`

**原因**: 输入或生成内容可能包含不安全或敏感内容，触发内容审查

**解决方案**:
- 检查输入提示词是否包含敏感内容
- 避免使用可能触发安全审核的词汇
- 调整提示词，使用更中性的表述

---

### invalid_request_error - 请求格式错误

**错误信息**: `Invalid request: {error_details}`

**原因**: 请求格式错误或缺少必要参数

**解决方案**:
- 检查请求体的 JSON 格式是否正确
- 确认所有必填参数都已提供
- 查看 `{error_details}` 获取具体错误原因

---

### invalid_request_error - Token 过长

**错误信息**: `Input token length too long`

**解决方案**:
- 减少输入的文本长度
- 使用摘要或截取关键信息
- 分批次处理长文本

---

### invalid_request_error - Token 超出模型限制

**错误信息**: `Your request exceeded model token limit: {max_model_length}`

**解决方案**:
- 请求的 tokens 数和 `max_tokens` 之和超过了模型规格限制
- 降低 `max_tokens` 参数值
- 选择支持更长上下文的模型（如 kimi-k2.5 支持 32K tokens）

---

### invalid_request_error - 目的参数错误

**错误信息**: `Invalid purpose: only 'file-extract' accepted`

**解决方案**:
- 仅使用 `purpose: "file-extract"` 上传文件
- 确认文件上传 API 的正确用法

---

### invalid_request_error - 文件过大

**错误信息**: `File size is too large, max file size is 100MB`

**解决方案**:
- 确保上传文件小于 100MB
- 压缩或分割大文件后上传

---

### invalid_request_error - 文件为空

**错误信息**: `File size is zero`

**解决方案**:
- 检查文件是否正确上传
- 确认文件路径和内容有效

---

### invalid_request_error - 上传文件数超限

**错误信息**: `The number of files you uploaded exceeded the max file count {max_file_count}`

**解决方案**:
- 删除不再需要的旧文件
- 分批次上传和管理文件

---

## 401 - 认证错误 (Authentication Error)

### invalid_authentication_error

**错误信息**: `Invalid Authentication`

**原因**: API Key 无效

**解决方案**:
- 检查 API Key 是否正确
- 确认 Key 没有多余的空格或字符
- 前往 [Kimi Platform](https://platform.kimi.ai) 获取正确的 Key

---

### incorrect_api_key_error

**错误信息**: `Incorrect API key provided`

**原因**: 提供的 API Key 错误

**解决方案**:
- 确认使用的是正确的 API Key
- 检查是否复制了完整的 Key
- **特别注意**: `platform.kimi.ai` 和 `platform.kimi.com` 的 Key 是独立的，不能混用

---

## 403 - 权限错误 (Permission Denied)

### permission_denied_error - API 未开放

**错误信息**: `The API you are accessing is not open`

**解决方案**:
- 确认该 API 是否已对您的账户开放
- 查看 Kimi 平台的 API 开放状态
- 等待 API 正式开放或联系支持

---

### permission_denied_error - 获取其他用户信息

**错误信息**: `You are not allowed to get other user info`

**解决方案**:
- 避免请求其他用户的私有数据
- 只访问自己账户下的资源

---

## 404 - 资源不存在

### resource_not_found_error

**错误信息**: `Not found the model {model-id} or Permission denied`

**解决方案**:
- 确认模型名称拼写正确
- 检查是否选择了有权限访问的模型
- 可用模型: `kimi-k2.5`, `kimi-latest` 等

---

## 429 - 限流 / 额度不足

### engine_overloaded_error

**错误信息**: `The engine is currently overloaded, please try again later`

**原因**: 当前并发请求过多，节点限流中

**解决方案**:
- 稍后重试
- 考虑升级账户 tier 以获得更高并发配额
- 实现请求队列和重试机制

---

### exceeded_current_quota_error - 账户停用

**错误信息**: `Your account {org-id}/{ak-id} is suspended`

**解决方案**:
- 检查账户余额
- 充值后恢复服务
- 查看账单详情

---

### exceeded_current_quota_error - Token 额度不足

**错误信息**: `You exceeded your current token quota: {org_id} {token_credit}`

**解决方案**:
- 账户余额不足
- 充值后继续使用
- 优化提示词减少 token 消耗

---

### rate_limit_reached_error - 并发限制

**错误信息**: `Your account reached organization max concurrency: {Concurrency}`

**解决方案**:
- 等待并发请求完成后重试
- 或在代码中实现请求排队机制

---

### rate_limit_reached_error - RPM 限制

**错误信息**: `Your account reached organization max RPM: {RPM}`

**解决方案**:
- 降低每分钟请求数
- 在请求间添加延迟 (`time.sleep()`)
- 查看 `{time}` 提示的等待时间

---

### rate_limit_reached_error - TPM 限制

**错误信息**: `Your account reached organization TPM rate limit, current:{current_tpm}, limit:{max_tpm}`

**解决方案**:
- TPM = 每分钟 Token 数限制
- 减少单次请求的 token 数量
- 降低请求频率

---

### rate_limit_reached_error - TPD 限制

**错误信息**: `Your account reached organization TPD rate limit, current:{current_tpd}, limit:{max_tpd}`

**解决方案**:
- TPD = 每日 Token 数限制
- 等待次日配额重置
- 或升级账户提高每日配额

---

## 500 - 服务端错误

### server_error

**错误信息**: `Failed to extract file: {error}`

**解决方案**:
- 文件解析失败
- 尝试重新上传文件
- 检查文件格式是否支持

---

### unexpected_output

**错误信息**: `invalid state transition`

**解决方案**:
- Kimi 服务器内部错误
- 稍后重试
- 如持续出现请联系 Kimi 支持团队

---

## 排障速查表

| 遇到的问题 | 首先检查 |
|-----------|---------|
| 401 错误 | API Key 是否正确？是否混用了不同平台的 Key？ |
| 429 错误 | 请求是否过于频繁？账户余额是否充足？ |
| 400 错误 | 请求格式是否正确？Token 是否超限？ |
| 500 错误 | 稍后重试，持续出现请联系支持 |

---

## 推荐实践

1. **实现重试机制**: 对 429、500 错误实现指数退避重试
2. **错误日志**: 记录完整的错误信息便于排查
3. **余额监控**: 设置余额提醒，避免服务中断
4. **熔断器模式**: 当错误率过高时暂停请求，避免浪费配额
5. **分批处理**: 大文本分批处理，避免超时和 Token 超限

---

> 参考文档: [Kimi API 错误说明](https://platform.kimi.com/docs/api/errors)
