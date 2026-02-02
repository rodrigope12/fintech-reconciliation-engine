import { FC, useState } from 'react';
import { ReconciliationResult, Match, api } from '../services/desktopApi';

interface ResultsViewProps {
  result: ReconciliationResult | null;
  clientName: string;
  onNewReconciliation: () => void;
}

type TabType = 'matched' | 'unmatched' | 'details';

export const ResultsView: FC<ResultsViewProps> = ({
  result,
  clientName,
  onNewReconciliation,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('matched');
  const [isExporting, setIsExporting] = useState(false);

  if (!result) {
    return (
      <div className="results-empty">
        <svg className="empty-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p>No hay resultados para mostrar</p>
      </div>
    );
  }

  const handleExport = async (format: 'xlsx' | 'csv' | 'pdf') => {
    setIsExporting(true);
    try {
      const blob = await api.exportResults(result.job_id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `conciliacion_${clientName}_${new Date().toISOString().split('T')[0]}.${format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Export failed:', error);
    } finally {
      setIsExporting(false);
    }
  };

  const matchRate = result.total_payments > 0
    ? (result.matched_count / result.total_payments * 100).toFixed(1)
    : '0';

  const formatCurrency = (cents: number) => {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: 'MXN',
    }).format(cents / 100);
  };

  return (
    <div className="results-view animate-fade-in">
      {/* Header */}
      <div className="results-header">
        <div className="results-title-row">
          <div>
            <h1 className="results-title">Resultados</h1>
            <p className="results-client">{clientName}</p>
          </div>
          <div className="results-actions">
            <button className="btn-macos btn-macos-secondary" onClick={onNewReconciliation}>
              Nueva Conciliación
            </button>
          </div>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="results-summary">
        <div className="card-macos stat-card stat-card-large">
          <div className="stat-icon icon-circle icon-circle-green">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div className="stat-value stat-value-success">{matchRate}%</div>
          <div className="stat-label">Tasa de Conciliación</div>
        </div>

        <div className="card-macos stat-card">
          <div className="stat-value">{result.matched_count}</div>
          <div className="stat-label">Pagos Conciliados</div>
          <div className="stat-total">de {result.total_payments}</div>
        </div>

        <div className="card-macos stat-card">
          <div className="stat-value">{result.total_invoices - result.unmatched_invoices}</div>
          <div className="stat-label">Facturas Usadas</div>
          <div className="stat-total">de {result.total_invoices}</div>
        </div>

        <div className="card-macos stat-card">
          <div className="stat-value stat-value-primary">{formatCurrency(result.total_reconciled_amount)}</div>
          <div className="stat-label">Monto Conciliado</div>
        </div>
      </div>

      {/* Status Badge */}
      <div className="results-status">
        {result.status === 'completed' ? (
          <span className="badge badge-success badge-large">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Completado en {result.processing_time_seconds.toFixed(1)}s
          </span>
        ) : result.status === 'partial' ? (
          <span className="badge badge-warning badge-large">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            Parcialmente completado
          </span>
        ) : (
          <span className="badge badge-error badge-large">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            Error en procesamiento
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="results-tabs">
        <div className="tab-buttons">
          <button
            className={`tab-button ${activeTab === 'matched' ? 'tab-button-active' : ''}`}
            onClick={() => setActiveTab('matched')}
          >
            Conciliados
            <span className="tab-count">{result.matches.length}</span>
          </button>
          <button
            className={`tab-button ${activeTab === 'unmatched' ? 'tab-button-active' : ''}`}
            onClick={() => setActiveTab('unmatched')}
          >
            Sin Conciliar
            <span className="tab-count">{result.unmatched_payments + result.unmatched_invoices}</span>
          </button>
          <button
            className={`tab-button ${activeTab === 'details' ? 'tab-button-active' : ''}`}
            onClick={() => setActiveTab('details')}
          >
            Detalles
          </button>
        </div>

        <div className="tab-content">
          {activeTab === 'matched' && (
            <MatchedTab matches={result.matches} formatCurrency={formatCurrency} />
          )}
          {activeTab === 'unmatched' && (
            <UnmatchedTab
              payments={result.unmatched_payment_ids}
              invoices={result.unmatched_invoice_ids}
            />
          )}
          {activeTab === 'details' && (
            <DetailsTab result={result} />
          )}
        </div>
      </div>

      {/* Export */}
      <div className="results-export">
        <div className="export-section">
          <h3 className="export-title">Exportar Resultados</h3>
          <div className="export-buttons">
            <button
              className="btn-macos btn-macos-secondary"
              onClick={() => handleExport('xlsx')}
              disabled={isExporting}
            >
              <svg className="btn-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Excel (.xlsx)
            </button>
            <button
              className="btn-macos btn-macos-secondary"
              onClick={() => handleExport('csv')}
              disabled={isExporting}
            >
              <svg className="btn-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              CSV
            </button>
            <button
              className="btn-macos btn-macos-secondary"
              onClick={() => handleExport('pdf')}
              disabled={isExporting}
            >
              <svg className="btn-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
              PDF
            </button>
          </div>
        </div>
      </div>

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <div className="results-warnings">
          <h4 className="warnings-title">
            <svg className="warning-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            Advertencias
          </h4>
          <ul className="warnings-list">
            {result.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

// Sub-components
const MatchedTab: FC<{ matches: Match[]; formatCurrency: (cents: number) => string }> = ({
  matches,
  formatCurrency,
}) => {
  if (matches.length === 0) {
    return (
      <div className="empty-state">
        <p>No hay transacciones conciliadas</p>
      </div>
    );
  }

  return (
    <div className="matches-table-container">
      <table className="table-macos">
        <thead>
          <tr>
            <th>Pago</th>
            <th>Facturas</th>
            <th className="text-right">Monto Pago</th>
            <th className="text-right">Monto Facturas</th>
            <th className="text-right">Diferencia</th>
            <th className="text-center">Confianza</th>
            <th className="text-center">Tipo</th>
          </tr>
        </thead>
        <tbody>
          {matches.map((match, index) => (
            <tr key={index}>
              <td className="font-mono text-xs">{match.payment_id.substring(0, 12)}...</td>
              <td className="font-mono text-xs">
                {match.invoice_ids.length} factura{match.invoice_ids.length !== 1 ? 's' : ''}
              </td>
              <td className="text-right">{formatCurrency(match.payment_amount)}</td>
              <td className="text-right">{formatCurrency(match.invoice_total)}</td>
              <td className={`text-right ${match.remainder !== 0 ? 'text-warning' : ''}`}>
                {match.remainder !== 0 ? formatCurrency(match.remainder) : '-'}
              </td>
              <td className="text-center">
                <span className={`badge ${match.confidence >= 0.9 ? 'badge-success' : match.confidence >= 0.7 ? 'badge-info' : 'badge-warning'}`}>
                  {(match.confidence * 100).toFixed(0)}%
                </span>
              </td>
              <td className="text-center">
                <span className="badge badge-info">{match.match_type}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const UnmatchedTab: FC<{ payments: string[]; invoices: string[] }> = ({
  payments,
  invoices,
}) => {
  return (
    <div className="unmatched-content">
      <div className="unmatched-section">
        <h4 className="unmatched-title">
          Pagos sin conciliar ({payments.length})
        </h4>
        {payments.length === 0 ? (
          <p className="text-success">Todos los pagos fueron conciliados</p>
        ) : (
          <ul className="unmatched-list">
            {payments.slice(0, 20).map((id, index) => (
              <li key={index} className="font-mono">{id}</li>
            ))}
            {payments.length > 20 && (
              <li className="more-items">Y {payments.length - 20} más...</li>
            )}
          </ul>
        )}
      </div>

      <div className="unmatched-section">
        <h4 className="unmatched-title">
          Facturas sin usar ({invoices.length})
        </h4>
        {invoices.length === 0 ? (
          <p className="text-success">Todas las facturas fueron usadas</p>
        ) : (
          <ul className="unmatched-list">
            {invoices.slice(0, 20).map((id, index) => (
              <li key={index} className="font-mono">{id}</li>
            ))}
            {invoices.length > 20 && (
              <li className="more-items">Y {invoices.length - 20} más...</li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
};

const DetailsTab: FC<{ result: ReconciliationResult }> = ({ result }) => {
  return (
    <div className="details-content">
      <div className="grouped-section">
        <h3 className="grouped-section-header">Información del Proceso</h3>

        <div className="grouped-item">
          <span className="detail-label">ID del Trabajo</span>
          <span className="detail-value font-mono">{result.job_id}</span>
        </div>

        <div className="grouped-item">
          <span className="detail-label">Cliente</span>
          <span className="detail-value">{result.client_name}</span>
        </div>

        <div className="grouped-item">
          <span className="detail-label">Estado</span>
          <span className={`badge ${result.status === 'completed' ? 'badge-success' : result.status === 'partial' ? 'badge-warning' : 'badge-error'}`}>
            {result.status}
          </span>
        </div>

        <div className="grouped-item">
          <span className="detail-label">Tiempo de Procesamiento</span>
          <span className="detail-value">{result.processing_time_seconds.toFixed(2)} segundos</span>
        </div>

        <div className="grouped-item">
          <span className="detail-label">Delta Total</span>
          <span className={`detail-value ${result.total_delta !== 0 ? 'text-warning' : 'text-success'}`}>
            {result.total_delta} centavos
          </span>
        </div>
      </div>

      <div className="grouped-section">
        <h3 className="grouped-section-header">Fases Completadas</h3>
        {result.phases_completed.map((phase, index) => (
          <div key={index} className="grouped-item">
            <span className="detail-label">Fase {index + 1}</span>
            <span className="detail-value">{phase}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
