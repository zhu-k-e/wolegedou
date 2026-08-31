import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 60000
})

// ===========================
// 响应拦截器：对 502/503/524 等网关错误自动重试
// Cloudflare Tunnel 偶尔会断连，重试可以大幅降低失败率
// ===========================
http.interceptors.response.use(
  response => response,
  async error => {
    const { config, response } = error;
    const status = response?.status;
    // 仅对网关类错误重试（502/503/504/524），最多重试 3 次
    const shouldRetry = (!response || status === 502 || status === 503 || status === 504 || status === 524)
      && config
      && (!config.__retryCount || config.__retryCount < 3);

    if (shouldRetry) {
      config.__retryCount = config.__retryCount || 0;
      config.__retryCount++;
      const waitMs = 1000 * config.__retryCount;
      console.warn(`请求失败(${status || '网络错误'})，${waitMs}ms 后第 ${config.__retryCount} 次重试...`);
      await new Promise(resolve => setTimeout(resolve, waitMs));
      return http(config);
    }
    return Promise.reject(error);
  }
);

/**
 * 提交学习任务（异步模式）
 *
 * 调用 POST /api/tasks，后端立即返回 task_id（实测 ~700ms），
 * 不阻塞等待 AI 推理完成。前端拿到 task_id 后通过 getTaskStatus 轮询结果。
 *
 * @param {Object} data - { question, goal, resources, session_id, history }
 * @returns {Promise<Object>} - { task_id, state }
 */
export async function askQuestion(data) {
  const res = await http.post('/tasks', data)
  return res.data
}

/**
 * 轮询任务状态
 *
 * 调用 GET /api/status/{task_id}，返回当前 FSM 状态和（完成后）完整结果。
 * state 流转：PENDING → PROFILING → DISPATCHING → GENERATING → REVIEWING
 *           → FOCUSING → JUDGING → FORMATTING → COMPLETE
 *
 * @param {string} taskId
 * @returns {Promise<Object>} - { task_id, state, result? }
 */
export async function getTaskStatus(taskId) {
  const res = await http.get(`/status/${taskId}`)
  return res.data
}

export async function submitFeedback(data) {
  const res = await http.post('/feedback', data)
  return res.data
}

export async function submitQuiz(data) {
  const res = await http.post('/quiz_submit', data)
  return res.data
}

export async function checkHealth() {
  const res = await http.get('/kb/health')
  return res.data
}

/**
 * 获取学情诊断报告（历史记录）
 *
 * 调用 GET /api/report/{session_id}，返回该会话累计的学情数据。
 * 包含三部分：知识盲区热力图、资源难度匹配曲线、学习路径规划。
 * 同一 session_id 多次提问后，报告会累积更新。
 *
 * @param {string} sessionId - 会话ID
 * @returns {Promise<Object>} - { session_id, profile_summary, knowledge_heatmap, difficulty_match, learning_path }
 * @throws {Error} 404 表示该 session 尚无学情数据（需要先提问）
 */
export async function getReport(sessionId) {
  const res = await http.get(`/report/${sessionId}`)
  return res.data
}

/**
 * 获取多智能体贡献记忆闭环数据
 *
 * 调用 GET /api/memory_stats，返回全系统累计的记忆贡献状态。
 * 包含：调度权重 α、Agent 表现排行、最近贡献流、淘汰记录。
 * 在任务 COMPLETE 后调用，展示「系统越用越聪明」的闭环效果。
 *
 * @returns {Promise<Object>} - { alpha, agent_count, agents[], recent_contributions[], eliminations[] }
 */
export async function getMemoryStats() {
  const res = await http.get('/memory_stats')
  return res.data
}
