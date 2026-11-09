import axios from 'axios'; import type { AIAnalysisResult, CapaAction, Investigation } from '../types';
export const api = axios.create({baseURL:import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1'});
export const investigationsApi = { list:()=>api.get<Investigation[]>('/investigations'), get:(id:number)=>api.get<Investigation>(`/investigations/${id}`), create:(data:Investigation)=>api.post<Investigation>('/investigations',data), update:(id:number,data:Investigation)=>api.put<Investigation>(`/investigations/${id}`,data) };
export const dashboardApi = { metrics:()=>api.get<{pending_capa_actions:number}>('/dashboard/metrics') };
export const aiApi = {
  analyzeText:(text:string,investigation_id:number)=>api.post<AIAnalysisResult>('/ai/analyze-text',{text,investigation_id}),
  analyzeEmail:(email_content:string,investigation_id:number)=>api.post<AIAnalysisResult>('/ai/analyze-email',{email_content,investigation_id}),
  analyzeDocument:(file:File,investigation_id:number,onProgress:(percent:number)=>void)=>{const data=new FormData();data.append('file',file);data.append('investigation_id',String(investigation_id));return api.post<AIAnalysisResult>('/ai/analyze-document',data,{onUploadProgress:e=>{if(e.total)onProgress(Math.round((e.loaded/e.total)*100))}})},
  retryAnalysis:(investigation_id:number)=>api.post<AIAnalysisResult>(`/ai/investigations/${investigation_id}/retry-analysis`),
};
export const capaApi = {
  list:(id:number)=>api.get<CapaAction[]>(`/investigations/${id}/capa`),
  create:(id:number,data:CapaAction)=>api.post<CapaAction>(`/investigations/${id}/capa`,data),
  update:(id:number,data:CapaAction)=>api.put<CapaAction>(`/capa/${id}`,data),
  remove:(id:number)=>api.delete(`/capa/${id}`),
  recommend:(id:number)=>api.post<{corrective_actions:CapaAction[];preventive_actions:CapaAction[]}>(`/investigations/${id}/capa/recommendations`),
  report:(id:number)=>api.get<Blob>(`/investigations/${id}/report`,{responseType:'blob'}),
};
