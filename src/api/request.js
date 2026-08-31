import axios from "axios";
const service = axios.create({
    baseURL: "/api",
    timeout: 120000
});
service.interceptors.request.use(config=>config);
service.interceptors.response.use(
  res => res, // 这里不能自动取data，否则空响应直接报错
  err => Promise.reject(err)
);
export default service;
