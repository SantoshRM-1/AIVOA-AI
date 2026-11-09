import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Clock3, FilePlus2, Search } from 'lucide-react';
import { dashboardApi, investigationsApi } from '../services/api';
import type { Investigation } from '../types';

function apiError(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    if (typeof response?.data?.detail === 'string') return response.data.detail;
  }
  return 'Could not connect to the API. Start the backend and check your connection.';
}

export function Dashboard() {
  const [items, setItems] = useState<Investigation[]>([]);
  const [pendingCapaActions, setPendingCapaActions] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([investigationsApi.list(), dashboardApi.metrics()])
      .then(([investigations, metrics]) => {
        setItems(investigations.data);
        setPendingCapaActions(metrics.data.pending_capa_actions);
        setError('');
      })
      .catch(reason => setError(apiError(reason)))
      .finally(() => setLoading(false));
  }, []);

  const completed = items.filter(item => item.status === 'Completed').length;
  const shown = (value: number) => (error ? '—' : value);

  return (
    <>
      <div className="heading-row">
        <div>
          <div className="eyebrow">OVERVIEW</div>
          <h1>Investigation dashboard</h1>
          <p className="subtitle">A clear view of quality investigations and follow-up.</p>
        </div>
        <Link className="button primary" to="/new">
          <FilePlus2 size={17} /> Create new investigation
        </Link>
      </div>
      <section className="stats">
        <div className="stat">
          <span>Total investigations</span>
          <b>{shown(items.length)}</b>
          <small>All recorded investigations</small>
        </div>
        <div className="stat">
          <span>Open investigations</span>
          <b>{shown(items.filter(item => item.status !== 'Completed').length)}</b>
          <small>In progress or awaiting review</small>
        </div>
        <div className="stat">
          <span>Completed</span>
          <b>{shown(completed)}</b>
          <small>Closed investigations</small>
        </div>
        <div className="stat">
          <span>Pending CAPA actions</span>
          <b>{shown(pendingCapaActions ?? 0)}</b>
          <small>Proposed, accepted or in-progress actions</small>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Recent investigations</h2>
            <p>Latest records saved to your workspace</p>
          </div>
          <span className="count-pill">{error ? '—' : `${items.length} records`}</span>
        </div>
        {error && <div className="notice error">{error}</div>}
        {loading ? (
          <div className="empty">
            <span className="spinner" /> Loading investigations…
          </div>
        ) : error ? (
          <div className="empty compact">Investigation records are unavailable until the API connection is restored.</div>
        ) : items.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">
              <Search />
            </div>
            <b>No investigations yet</b>
            <span>Create an investigation to begin documenting a deviation.</span>
            <Link to="/new" className="button secondary">
              Create investigation <ArrowRight size={15} />
            </Link>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>DEVIATION</th>
                  <th>INCIDENT</th>
                  <th>PRODUCT / API</th>
                  <th>DATE</th>
                  <th>STATUS</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map(item => (
                  <tr key={item.id}>
                    <td className="mono">{item.deviation_id || `INV-${item.id}`}</td>
                    <td>
                      <Link to={`/workspace/${item.id}`} className="table-link">
                        {item.incident_title || 'Untitled investigation'}
                      </Link>
                    </td>
                    <td>{item.product_name || '—'}</td>
                    <td>{item.incident_date || '—'}</td>
                    <td>
                      <span className="status">{item.status}</span>
                    </td>
                    <td>
                      <Link to={`/workspace/${item.id}`} className="icon-link">
                        <ArrowRight size={16} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div className="demo-note">
        <Clock3 size={15} /> Live investigation records are loaded from the configured API.
      </div>
    </>
  );
}
