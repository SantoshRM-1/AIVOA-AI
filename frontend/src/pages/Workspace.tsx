import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowDown, Plus, Save, Sparkles, Trash2 } from 'lucide-react';
import { Field } from '../components/Field';
import { investigationsApi } from '../services/api';
import { emptyInvestigation, type Evidence, type FiveWhyItem, type Investigation, type MissingEvidenceSuggestion, type RootCauseAnalysis, type RootCauseSuggestion } from '../types';

const categories = ['Man / People', 'Machine / Equipment', 'Method / Process', 'Material', 'Measurement', 'Mother Nature / Environment'];
const labels: Record<string, string> = {
  deviation_id: 'Deviation ID', incident_title: 'Incident title', product_name: 'Product / API name', batch_number: 'Batch number',
  department: 'Department', manufacturing_stage: 'Manufacturing stage', deviation_category: 'Deviation category',
  equipment_involved: 'Equipment involved', incident_date: 'Incident date', expected_condition: 'Expected condition',
  actual_condition: 'Actual condition', incident_description: 'Incident description', immediate_actions: 'Immediate actions',
  potential_quality_impact: 'Potential quality impact',
};
const extractionKey: Record<string, string> = { product_name: 'product_api_name' };
const defaultWhys: FiveWhyItem[] = [];

function messageFrom(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    if (typeof response?.data?.detail === 'string') return response.data.detail;
  }
  return 'Could not load the investigation. Check the backend and database connection.';
}

function asEvidence(item: Evidence): Evidence { return { description: item.description, source_reference: item.source_reference, available: item.available, file_name: item.file_name, mime_type: item.mime_type }; }

export function Workspace() {
  const { id } = useParams();
  const nav = useNavigate();
  const [form, setForm] = useState<Investigation>(emptyInvestigation);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [missingEvidence, setMissingEvidence] = useState<MissingEvidenceSuggestion[]>([]);
  const [rca, setRca] = useState<RootCauseAnalysis | null>(null);
  const [whys, setWhys] = useState<FiveWhyItem[]>(defaultWhys);
  const [causes, setCauses] = useState<Record<string, string[]>>(Object.fromEntries(categories.map(category => [category, []])));
  const [userEdited, setUserEdited] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(Boolean(id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [evidenceText, setEvidenceText] = useState('');
  const [evidenceSource, setEvidenceSource] = useState('');
  const missingInformation = useMemo(() => rca?.extraction_data?.missing_information ?? [], [rca]);

  const loadRecord = (record: Investigation) => {
    setForm({ ...emptyInvestigation, ...record });
    setEvidence((record.evidence ?? []).filter(item => item.available).map(asEvidence));
    setMissingEvidence((record.evidence ?? []).filter(item => !item.available).map(item => {
      const prefix = 'Suggested evidence: ';
      const detail = item.description.startsWith(prefix) ? item.description.slice(prefix.length) : item.description;
      const [description, ...reasonParts] = detail.split(' — ');
      return { description, reason: reasonParts.join(' — '), suggested_source: item.source_reference, status: 'Suggested' as const };
    }));
    const stored = record.rca ?? null;
    setRca(stored);
    setWhys(stored?.five_whys ?? []);
    const fishbone = stored?.fishbone ?? {};
    setCauses(Object.fromEntries(categories.map(category => [category, fishbone[category] ?? []])));
  };

  useEffect(() => {
    if (!id) { setLoading(false); return; }
    investigationsApi.get(Number(id)).then(response => loadRecord(response.data)).catch(reason => setError(messageFrom(reason))).finally(() => setLoading(false));
  }, [id]);

  const extraction = rca?.extraction_data;
  const change = (key: keyof Investigation, value: string) => {
    setForm(current => ({ ...current, [key]: value }));
    setUserEdited(current => ({ ...current, [key]: true }));
    const modelKey = extractionKey[key] ?? key;
    setRca(current => {
      if (!current?.extraction_data) return current;
      const prior = current.extraction_data[modelKey as keyof typeof current.extraction_data];
      if (!prior || typeof prior !== 'object' || !('status' in prior)) return current;
      return { ...current, extraction_data: { ...current.extraction_data, [modelKey]: { ...prior, review_status: 'User Edited' } } };
    });
    setSaved(false);
  };

  const fieldMeta = (key: string) => {
    const modelKey = extractionKey[key] ?? key;
    const meta = extraction?.[modelKey as keyof typeof extraction];
    if (!meta || typeof meta !== 'object' || !('status' in meta)) return null;
    const status = meta.review_status ?? (userEdited[key] ? 'User Edited' : meta.status === 'Missing' ? 'Missing' : meta.status === 'Extracted' ? 'AI Extracted' : 'Needs Verification');
    const page = 'source_page' in meta ? meta.source_page : null;
    const quote = 'supporting_text' in meta ? meta.supporting_text : null;
    return { status, page, quote };
  };

  const save = async () => {
    if (!form.deviation_id.trim() || !form.incident_title.trim()) {
      setSaved(false); setError('Deviation ID and incident title are required before saving.'); return;
    }
    if (rca?.suggestions.some(s => ['Confirmed by Human Reviewer', 'Rejected'].includes(s.status) && !s.reviewer_note?.trim())) {
      setSaved(false); setError('Add a human review explanation to every confirmed or rejected root cause.'); return;
    }
    setBusy(true); setError(''); setSaved(false);
    const payload: Investigation = {
      ...form,
      incident_date: form.incident_date || null,
      evidence: [
        ...evidence.filter(item => !item.file_name).map(item => ({ ...asEvidence(item), available: true })),
        ...missingEvidence.map(item => ({ description: `Suggested evidence: ${item.description} — ${item.reason}`, source_reference: item.suggested_source, available: false })),
      ],
      rca: rca ? { ...rca, five_whys: whys, fishbone: causes } : null,
    };
    try {
      const response = form.id ? await investigationsApi.update(form.id, payload) : await investigationsApi.create(payload);
      loadRecord(response.data);
      if (!form.id) nav(`/workspace/${response.data.id}`, { replace: true });
      setSaved(true);
    } catch (reason) { setError(messageFrom(reason)); }
    finally { setBusy(false); }
  };

  if (loading) return <div className="empty"><span className="spinner"/> Loading investigation…</div>;
  const hasAIResults = Boolean(rca?.extraction_data && Object.values(rca.extraction_data).some(value => value && typeof value === 'object' && 'status' in value));

  return <>
    <div className="eyebrow">INVESTIGATIONS / WORKSPACE</div>
    <div className="heading-row"><div><h1>Investigation review</h1><p className="subtitle">Review the extracted facts and evidence, correct anything that needs editing, then save.</p></div><button className="button primary" onClick={save} disabled={busy}><Save size={16}/>{busy ? 'Saving…' : 'Save investigation'}</button></div>
    {error && <div className="notice error">{error}</div>}{saved && <div className="notice success">Investigation and AI analysis saved to the database.</div>}
    {hasAIResults && <div className="ai-note review-instruction"><div className="ai-glyph"><Sparkles size={17}/></div><div><b>Review and correct the extracted information. Then examine the potential root causes and evidence before continuing.</b><span>AI suggestions are not confirmed conclusions. Your edits are saved with the investigation.</span></div></div>}

    <section className="panel workspace-panel" id="deviation-information"><div className="section-title"><span className="section-num">01</span><div><h2>Extracted information</h2><p>Editable investigation facts. Source quotes and PDF pages are shown when available.</p></div><button className="button secondary compact-action" onClick={() => document.getElementById('deviation-information')?.scrollIntoView({ behavior: 'smooth' })}>Edit information</button></div>
      <div className="field-grid">{Object.entries(labels).map(([key, label]) => {
        const meta = fieldMeta(key);
        const value = form[key as keyof Investigation];
        return <div className="review-field" key={key}><Field label={label}>{['incident_description', 'expected_condition', 'actual_condition', 'immediate_actions', 'potential_quality_impact', 'equipment_involved'].includes(key)
          ? <textarea rows={key === 'incident_description' ? 4 : 2} value={String(value ?? '')} onChange={event => change(key as keyof Investigation, event.target.value)}/>
          : <input type={key === 'incident_date' ? 'date' : 'text'} value={String(value ?? '')} onChange={event => change(key as keyof Investigation, event.target.value)}/>}</Field>
          {meta && <div className="field-provenance"><span className={`ai-status ${meta.status.toLowerCase().replace(/ /g, '-')}`}>{meta.status}</span>{meta.page && <span>Page {meta.page}</span>}{meta.quote && <span className="source-quote">“{meta.quote}”</span>}</div>}
        </div>;
      })}</div>
    </section>

    <section className="panel workspace-panel"><div className="section-title"><span className="section-num">02</span><div><h2>Evidence</h2><p>Available source evidence and suggested records to verify the investigation.</p></div></div>
      <div className="evidence-grid"><div className="evidence-box"><div className="evidence-head"><b>Available evidence</b><span className="evidence-status">{evidence.length} items</span></div>
        {evidence.length === 0 ? <p>No evidence entries recorded yet.</p> : evidence.map((item, index) => <div className="evidence-entry" key={`${item.source_reference}-${index}`}><b>{item.description}</b>{item.source_reference && <small>{item.source_reference}</small>}</div>)}
        <Field label="Evidence description"><input value={evidenceText} onChange={event => setEvidenceText(event.target.value)} placeholder="Describe the evidence"/></Field><Field label="Source reference"><input value={evidenceSource} onChange={event => setEvidenceSource(event.target.value)} placeholder="Document ID, record or page"/></Field>
        <button className="text-button" onClick={() => { if (evidenceText.trim()) setEvidence(items => [...items, { description: evidenceText.trim(), source_reference: evidenceSource.trim() || null, available: true }]); setEvidenceText(''); setEvidenceSource(''); }}><Plus size={14}/> Add available evidence</button>
      </div><div className="evidence-box missing"><div className="evidence-head"><b>Missing evidence suggestions</b><span className="evidence-status">Not claims that records exist</span></div>
        {missingEvidence.length === 0 ? <p>No missing evidence suggestions were returned.</p> : missingEvidence.map((item, index) => <div className="evidence-entry" key={`${item.description}-${index}`}><b>{item.description}</b><small>{item.reason}</small>{item.suggested_source && <small>Possible source: {item.suggested_source}</small>}</div>)}
        {missingInformation.length > 0 && <div className="missing-information"><b>Information to verify</b>{missingInformation.map((item, index) => <p key={`${item.field_name}-${index}`}><strong>{item.field_name.replace(/_/g, ' ')}</strong>: {item.reason}{item.suggested_followup ? ` ${item.suggested_followup}` : ''}</p>)}</div>}
      </div></div>
    </section>

    <section className="panel workspace-panel"><div className="section-title"><span className="section-num">03</span><div><h2>Five Whys</h2><p>Suggested questions and supported answers. Unsupported answers remain open for investigation.</p></div></div>
      {whys.length === 0 ? <div className="empty compact">No Five Whys suggestions returned. The incident description is available above for manual investigation.</div> : <div className="whys-list">{whys.map((why, index) => <div className="why-row" key={index}><div className="why-index">0{index + 1}</div><div className="why-fields"><Field label="Question"><input value={why.question} onChange={event => setWhys(items => items.map((item, row) => row === index ? { ...item, question: event.target.value } : item))}/></Field><Field label="Answer"><textarea rows={2} placeholder="Needs investigation when the evidence does not support an answer" value={why.answer ?? ''} onChange={event => setWhys(items => items.map((item, row) => row === index ? { ...item, answer: event.target.value || null, status: event.target.value ? item.status : 'Needs Investigation' } : item))}/></Field><span className={`ai-status ${why.status.toLowerCase().replace(/ /g, '-')}`}>{why.status}</span>{why.supporting_evidence.map((ref, refIndex) => <small className="source-quote" key={refIndex}>{ref.source_page ? `Page ${ref.source_page} · ` : ''}{ref.excerpt}</small>)}</div></div>)}</div>}
    </section>

    <section className="panel workspace-panel"><div className="section-title"><span className="section-num">04</span><div><h2>Fishbone analysis</h2><p>Possible causes are suggestions. Matched evidence and missing evidence are shown for AI hypotheses.</p></div></div><div className="fish-grid">{categories.map(category => <div className="fish-card" key={category}><b>{category}</b>{(causes[category] ?? []).map((cause, index) => {const linked=rca?.suggestions.find(s=>s.category===category&&s.cause_description===cause);return <div className="cause-row" key={index}><div className="cause-detail"><input value={cause} placeholder="Possible cause" onChange={event => setCauses(current => ({ ...current, [category]: current[category].map((value, row) => row === index ? event.target.value : value) }))}/>{linked&&<><span className={`ai-status ${linked.status.toLowerCase().replace(/ /g,'-')}`}>{linked.status}</span>{linked.supporting_evidence.map((ref,i)=><small key={i}>{ref.source_page?`Page ${ref.source_page} · `:''}{ref.excerpt}</small>)}{linked.missing_evidence.length>0&&<small>Missing evidence: {linked.missing_evidence.join('; ')}</small>}</>}</div><button className="icon-link" aria-label="Remove possible cause" onClick={() => setCauses(current => ({ ...current, [category]: current[category].filter((_, row) => row !== index) }))}><Trash2 size={15}/></button></div>})}<button className="text-button" onClick={() => setCauses(current => ({ ...current, [category]: [...(current[category] ?? []), ''] }))}><Plus size={14}/> Add possible cause</button></div>)}</div></section>

    <section className="panel workspace-panel" id="root-cause-analysis"><div className="section-title"><span className="section-num">05</span><div><h2>Root cause suggestions</h2><p>AI hypotheses require evidence review and human confirmation.</p></div><button className="button secondary compact-action" onClick={() => document.getElementById('root-cause-analysis')?.scrollIntoView({ behavior: 'smooth' })}><ArrowDown size={14}/> Continue to RCA</button></div>
      {!rca?.suggestions?.length ? <div className="suggestion-empty"><Sparkles size={19}/><div><b>No root cause suggestions returned</b><span>Review the facts and evidence above. This workspace does not create automatic conclusions.</span></div></div> : <div className="root-suggestion-list">{rca.suggestions.map((suggestion: RootCauseSuggestion, index) => <article className="root-suggestion" key={`${suggestion.category}-${index}`}><div className="suggestion-title"><span className="category-pill">{suggestion.category}</span><select aria-label="Root cause review status" value={suggestion.status} onChange={event => setRca(current => current ? { ...current, suggestions: current.suggestions.map((item, row) => row === index ? { ...item, status: event.target.value as RootCauseSuggestion['status'] } : item) } : current)}><option>Suggested</option><option>Needs Investigation</option><option>Evidence Supported</option><option>Confirmed by Human Reviewer</option><option>Rejected</option></select></div><h3>{suggestion.cause_description}</h3><p>{suggestion.explanation}</p>{suggestion.supporting_evidence.length > 0 && <div className="suggestion-evidence"><b>Supporting source</b>{suggestion.supporting_evidence.map((reference, refIndex) => <span key={refIndex}>{reference.source_page ? `Page ${reference.source_page} · ` : ''}{reference.excerpt}</span>)}</div>}{suggestion.missing_evidence.length > 0 && <div className="suggestion-evidence"><b>Evidence to obtain</b><span>{suggestion.missing_evidence.join('; ')}</span></div>}<small className="verification-question">Verification question: {suggestion.verification_question}</small>{['Confirmed by Human Reviewer','Rejected'].includes(suggestion.status)&&<Field label="Human review explanation (required)"><textarea value={suggestion.reviewer_note??''} onChange={event=>setRca(current=>current?{...current,suggestions:current.suggestions.map((item,row)=>row===index?{...item,reviewer_note:event.target.value}:item)}:current)}/></Field>}</article>)}</div>}
    </section>
    <div className="action-title"><p className="quiet">AI-generated information must be reviewed and approved by a qualified human reviewer.</p><button className="button primary" onClick={()=>id?nav(`/capa?id=${id}`):setError('Save the investigation before opening CAPA.')}>Continue to CAPA</button></div>
  </>;
}
