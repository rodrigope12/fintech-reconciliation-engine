import { FC, useState, useEffect, useCallback } from 'react';
import { api } from '../services/desktopApi';

interface ReconciliationProgressProps {
  clientName: string;
  jobId: string;
  onComplete: () => void;
  onError: (error: string) => void;
}

interface Phase {
  id: string;
  name: string;
  description: string;
  status: 'pending' | 'active' | 'completed';
}

const PHASE_MAPPING: Record<string, number> = {
  'Iniciando...': 0,
  'Procesando estados de cuenta...': 0,
  'Procesando facturas CFDI...': 1,
  'Calculando similitud de textos...': 2,
  'Safe Peeling (Fase 0)...': 3,
  'Clustering Leiden (Fase 1)...': 4,
  'Resolviendo MILP (Fase 2)...': 5,
  'Rescue Loop (Fase 3):': 5,
  'Generando reporte...': 5,
  'Completado': 6,
};

export const ReconciliationProgress: FC<ReconciliationProgressProps> = ({
  clientName,
  jobId,
  onComplete,
  onError,
}) => {
  const [phases, setPhases] = useState<Phase[]>([
    { id: 'ocr', name: 'OCR', description: 'Extrayendo datos de PDFs bancarios', status: 'pending' },
    { id: 'parse', name: 'Parseo CFDI', description: 'Procesando facturas XML', status: 'pending' },
    { id: 'embeddings', name: 'Embeddings', description: 'Calculando similitud semántica', status: 'pending' },
    { id: 'peeling', name: 'Safe Peeling', description: 'Matching de alta confianza', status: 'pending' },
    { id: 'clustering', name: 'Clustering', description: 'Particionando transacciones', status: 'pending' },
    { id: 'solver', name: 'Solver MILP', description: 'Optimización matemática', status: 'pending' },
  ]);

  const [currentMessage, setCurrentMessage] = useState('Conectando con el servidor...');
  const [progress, setProgress] = useState(0);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [isPolling, setIsPolling] = useState(true);

  // Timer for elapsed time
  useEffect(() => {
    const interval = setInterval(() => {
      setElapsedTime(prev => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Poll backend for real status
  const pollStatus = useCallback(async () => {
    if (!jobId || !isPolling) return;

    try {
      const status = await api.getStatus(jobId);

      setProgress(status.progress);
      setCurrentMessage(status.current_phase || 'Procesando...');

      // Update phases based on current phase
      const currentPhaseKey = Object.keys(PHASE_MAPPING).find(key =>
        status.current_phase?.includes(key) || status.current_phase?.startsWith(key.replace('...', ''))
      );

      const currentPhaseIndex = currentPhaseKey ? PHASE_MAPPING[currentPhaseKey] : -1;

      setPhases(prev => prev.map((phase, idx) => ({
        ...phase,
        status: idx < currentPhaseIndex ? 'completed' : idx === currentPhaseIndex ? 'active' : 'pending',
      })));

      // Check if completed or failed
      if (status.status === 'completed') {
        setIsPolling(false);
        setPhases(prev => prev.map(phase => ({ ...phase, status: 'completed' })));
        setTimeout(() => onComplete(), 1000);
      } else if (status.status === 'failed') {
        setIsPolling(false);
        onError(status.message || 'Error en el procesamiento');
      }
    } catch (error) {
      console.error('Error polling status:', error);
      // Don't stop polling on temporary errors
    }
  }, [jobId, isPolling, onComplete, onError]);

  // Polling interval
  useEffect(() => {
    if (!isPolling) return;

    // Initial poll
    pollStatus();

    // Poll every 2 seconds
    const interval = setInterval(pollStatus, 2000);
    return () => clearInterval(interval);
  }, [pollStatus, isPolling]);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="progress-screen animate-fade-in">
      {/* Header */}
      <div className="progress-header">
        <div className="progress-icon-container">
          <div className="progress-icon-ring">
            <svg className="progress-ring-svg" viewBox="0 0 100 100">
              <circle
                className="progress-ring-bg"
                cx="50"
                cy="50"
                r="45"
                fill="none"
                strokeWidth="8"
              />
              <circle
                className="progress-ring-fill"
                cx="50"
                cy="50"
                r="45"
                fill="none"
                strokeWidth="8"
                strokeDasharray={`${progress * 2.83} 283`}
                transform="rotate(-90 50 50)"
              />
            </svg>
            <span className="progress-percentage">{Math.round(progress)}%</span>
          </div>
        </div>
        <h1 className="progress-title">Procesando</h1>
        <p className="progress-client">{clientName}</p>
        <p className="progress-time">Tiempo transcurrido: {formatTime(elapsedTime)}</p>
      </div>

      {/* Current Operation */}
      <div className="current-operation">
        <div className="operation-indicator">
          <div className="spinner-macos" />
          <span className="operation-text">{currentMessage}</span>
        </div>
      </div>

      {/* Phases */}
      <div className="phases-container">
        <div className="grouped-section">
          {phases.map((phase, index) => (
            <div
              key={phase.id}
              className={`phase-item ${phase.status === 'active' ? 'phase-item-active' : ''}`}
            >
              <div className="phase-status">
                {phase.status === 'completed' ? (
                  <div className="phase-check">
                    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                ) : phase.status === 'active' ? (
                  <div className="phase-spinner">
                    <div className="spinner-macos spinner-small" />
                  </div>
                ) : (
                  <div className="phase-number">{index + 1}</div>
                )}
              </div>

              <div className="phase-content">
                <div className="phase-header">
                  <span className="phase-name">{phase.name}</span>
                </div>
                <span className="phase-description">{phase.description}</span>
                {phase.status === 'active' && (
                  <div className="progress-macos">
                    <div
                      className="progress-macos-bar progress-macos-bar-indeterminate"
                    />
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="overall-progress">
        <div className="progress-macos">
          <div
            className="progress-macos-bar"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="progress-label">{Math.round(progress)}% completado</p>
      </div>

      {/* Technical Details */}
      <div className="tech-details">
        <details className="details-panel">
          <summary className="details-summary">
            <svg className="details-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            Detalles técnicos
          </summary>
          <div className="details-content">
            <div className="detail-row">
              <span className="detail-label">Job ID:</span>
              <span className="detail-value">{jobId}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Solver:</span>
              <span className="detail-value">HiGHS (MILP)</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Algoritmo:</span>
              <span className="detail-value">Lexicográfico 3 fases</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Clustering:</span>
              <span className="detail-value">Leiden (resolution=1.0)</span>
            </div>
          </div>
        </details>
      </div>
    </div>
  );
};
