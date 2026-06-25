import axios from 'axios';

const api = axios.create({
  // Use same origin so the frontend works regardless of port, unless explicitly overridden.
  baseURL: import.meta.env.VITE_API_URL ?? window.location.origin,
  withCredentials: true,
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !window.location.pathname.endsWith('/login')) {
      window.location.href = '/app/login';
    }
    return Promise.reject(error);
  }
);

export default api;
