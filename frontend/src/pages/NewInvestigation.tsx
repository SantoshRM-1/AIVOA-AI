import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, FileText, Mail, Sparkles, UploadCloud, X } from 'lucide-react';
import { investigationsApi, aiApi } from '../services/api';
import { emptyInvestigation } from '../types';

type Tab = 'description' | 'email' | 'pdf';

function apiError(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    if (typeof response?.data?.detail === 'string') return response.data.detail;
  }
  if (error instanceof Error && error.message) return error.message;
  return 'Could not connect to the AIVOA API. Check that the backend and PostgreSQL are available.';
}

function apiStatus(error: unknown): number | undefined {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { status?: unknown } }).response;
    if (typeof response?.status === 'number') return response.status;
  }
  return undefined;
}

export function NewInvestigation() {
  const [tab, setTab] = useState<Tab>('description');
  const [content, setContent] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [draftId, setDraftId] = useState<number | null>(null);
  const [draftTab, setDraftTab] = useState<Tab | null>(null);
  const [statusMessage, setStatusMessage] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const analysisInFlight = useRef(false);
  const nav = useNavigate();

  const chooseFile = (candidate?: File) => {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.pdf') || (candidate.type && candidate.type !== 'application/pdf')) {
      setError('Please choose a PDF document.');
      return;
    }
    if (!candidate.size || candidate.size > 20 * 1024 * 1024) {
      setError(candidate.size ? 'PDF documents must be 20 MB or smaller.' : 'The selected PDF is empty.');
      return;
    }
    setError('');
    setFile(candidate);
  };

  const analyze = async () => {
    if (analysisInFlight.current) return;
    if (!draftId && tab === 'pdf' && !file) return setError('Choose a PDF document first.');
    if (!draftId && tab !== 'pdf' && !content.trim()) return setError('Enter incident information before analysis.');
    analysisInFlight.current = true;
    setBusy(true);
    setError('');
    setUploadProgress(null);
    setStatusMessage(draftId ? 'Retrying analysis from the saved source…' : 'Saving the source in a new investigation…');
    let currentDraftId = draftId;
    try {
      const analyzeCurrentSource = async (investigationId: number, sourceTab: Tab) => {
        setStatusMessage(sourceTab === 'pdf' ? 'Uploading PDF to the analysis service…' : 'Analyzing incident information with Gemini…');
        if (sourceTab === 'pdf') {
          if (!file) throw new Error('The saved PDF was not found. Select the original PDF and retry.');
          await aiApi.analyzeDocument(file, investigationId, percent => {
            setUploadProgress(percent);
            if (percent >= 100) setStatusMessage('PDF uploaded. Extracting selectable text and running the analysis…');
          });
        } else if (sourceTab === 'email') {
          await aiApi.analyzeEmail(content.trim(), investigationId);
        } else {
          await aiApi.analyzeText(content.trim(), investigationId);
        }
      };
      if (!currentDraftId) {
        const sourceText = tab === 'pdf' ? `Uploaded incident report: ${file!.name}` : content.trim();
        const title = tab === 'email' ? 'Email incident report' : tab === 'pdf' ? 'PDF incident report' : 'New investigation';
        const record = await investigationsApi.create({
          ...emptyInvestigation,
          deviation_id: `DEV-${Date.now()}-${crypto.randomUUID().slice(0, 8)}`,
          incident_title: title,
          incident_description: sourceText,
        });
        currentDraftId = record.data.id!;
        setDraftId(currentDraftId);
        setDraftTab(tab);
        await analyzeCurrentSource(currentDraftId, tab);
      } else {
        try {
          await aiApi.retryAnalysis(currentDraftId);
        } catch (reason) {
          const noSavedSource = apiStatus(reason) === 404 && apiError(reason).startsWith('No saved incident source');
          if (!noSavedSource) throw reason;
          await analyzeCurrentSource(currentDraftId, draftTab ?? tab);
        }
      }
      setStatusMessage('Analysis complete. Opening the editable review workspace…');
      nav(`/workspace/${currentDraftId}`);
    } catch (reason) {
      setError(apiError(reason));
      setStatusMessage(currentDraftId ? 'Your investigation draft and selected source remain available. Retry Analysis will reuse the saved source when available.' : '');
    } finally {
      analysisInFlight.current = false;
      setBusy(false);
      setUploadProgress(null);
    }
  };

  return <>
    <div className="eyebrow">INVESTIGATIONS / NEW</div>
    <h1>Start an investigation</h1>
    <p className="subtitle">Add an incident source and use Gemini to extract facts and prepare an evidence-led RCA for review.</p>
    <div className="stepper"><div className="step active"><i>1</i><span>Incident input</span></div><div className="step-line"/><div className="step"><i>2</i><span>Review & investigate</span></div><div className="step-line"/><div className="step"><i>3</i><span>CAPA</span></div></div>
    <section className="panel input-panel">
      <div className="panel-head"><div><h2>Incident source</h2><p>Choose the format that best fits the information available.</p></div><span className="required">Required</span></div>
      <div className="tabs">
        <button className={tab === 'description' ? 'selected' : ''} onClick={() => { setTab('description'); if (!draftId) setError(''); }}><FileText size={16}/> Incident description</button>
        <button className={tab === 'email' ? 'selected' : ''} onClick={() => { setTab('email'); if (!draftId) setError(''); }}><Mail size={16}/> Email content</button>
        <button className={tab === 'pdf' ? 'selected' : ''} onClick={() => { setTab('pdf'); if (!draftId) setError(''); }}><UploadCloud size={16}/> PDF document</button>
      </div>
      {tab !== 'pdf' ? <div className="source-input">
        <textarea value={content} onChange={event => setContent(event.target.value)} placeholder={tab === 'email' ? 'Paste the relevant email content, including subject, sender and date…' : 'Describe what happened, when it occurred, the affected product or batch, and any immediate response…'}/>
        <div className="textarea-foot"><span>{content.length} characters</span><span>Information not stated in the source will remain missing.</span></div>
      </div> : <>
        <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={event => chooseFile(event.target.files?.[0])}/>
        {file ? <div className="file-ready"><div className="file-symbol"><FileText/></div><div><b>{file.name}</b><small>{(file.size / 1024 / 1024).toFixed(2)} MB · PDF document</small></div><button className="icon-link" aria-label="Remove document" onClick={() => { setFile(null); if (input.current) input.current.value = ''; }}><X size={18}/></button></div>
          : <button className="dropzone" onClick={() => input.current?.click()} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); chooseFile(event.dataTransfer.files[0]); }}><span className="upload-icon"><UploadCloud/></span><b>Drop your report here, or <u>browse files</u></b><span>PDF only · Maximum 20 MB · Text PDFs only (no OCR)</span></button>}
      </>}
      {error && <div className="notice error">{error}</div>}
      {statusMessage && <div className="notice success">{statusMessage}{uploadProgress !== null && <><div className="upload-meter"><i style={{ width: `${uploadProgress}%` }}/></div><small>{uploadProgress}% uploaded</small></>}</div>}
      <div className="ai-note"><div className="ai-glyph"><Sparkles size={17}/></div><div><b>AI suggestions are for human review</b><span>Extracted values include source references where available. No cause is automatically confirmed.</span></div></div>
      <div className="form-actions"><span className="quiet">Gemini configuration is read only by the backend.</span><button className="button primary" disabled={busy} aria-busy={busy} onClick={analyze}>{busy ? <><span className="spinner light"/> Analyzing…</> : <><Sparkles size={16}/> {draftId && error ? 'Retry Analysis' : 'Analyze incident with AI'}</>} {!busy && <ArrowRight size={16}/>}</button></div>
    </section>
  </>;
}
