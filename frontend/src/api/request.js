import axios from 'axios'
import { ElMessage } from 'element-plus'

// API 基础地址（使用相对路径，让 Vite 代理生效）
const baseURL = import.meta.env.VITE_API_BASE_URL || '/api'

const request = axios.create({
  baseURL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 记录上一次的错误信息，避免重复弹窗
let lastErrorMsg = ''
let lastErrorTime = 0

function shouldShowError(msg) {
  const now = Date.now()
  // 5秒内相同的错误不重复弹窗
  if (msg === lastErrorMsg && (now - lastErrorTime) < 5000) {
    return false
  }
  lastErrorMsg = msg
  lastErrorTime = now
  return true
}

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    const { code, message, data } = response.data
    if (code !== 200) {
      // 业务错误只在非静音模式下提示
      if (shouldShowError(message)) {
        ElMessage.warning(message || '请求失败')
      }
      return Promise.reject(new Error(message))
    }
    return data
  },
  (error) => {
    // 网络错误静默处理（刷新时后端可能还没就绪）
    if (!error.response) {
      // 后端未启动或网络不通，静默返回，不弹窗
      console.warn('网络请求失败:', error.message)
      return Promise.reject(error)
    }
    
    // HTTP 错误
    const msg = error.response?.data?.message || `HTTP ${error.response.status}`
    if (shouldShowError(msg)) {
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  }
)

export default request
