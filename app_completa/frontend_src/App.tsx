import { useState, useEffect } from 'react';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api';
import './styles/macos.css';
import { ValidationScreen } from './components/ValidationScreen';
import { ClientSelector } from './components/ClientSelector';
import { ReconciliationProgress } from './components/ReconciliationProgress';
import { ResultsView } from './components/ResultsView';
import { SettingsPanel } from './components/SettingsPanel';
import { Sidebar } from './components/Sidebar';
import { api, ScanResult, ValidationResult, ReconciliationResult } from './services/desktopApi';

type AppView = 'validation' | 'selector' | 'processing' | 'results' | 'settings';

interface AppState {
  currentView: AppView;
  isValidated: boolean;
  scanResult: ScanResult | null;
  selectedClient: string | null;
  reconciliationResult: ReconciliationResult | null;
  validationResult: ValidationResult | null;
  currentJobId: string | null;
  logs: string[];
}

export default function App() {
  const [state, setState] = useState<AppState>({
    currentView: 'validation',
    isValidated: false,
    scanResult: null,
    selectedClient: null,
    reconciliationResult: null,
    validationResult: null,
    currentJobId: null,
    logs: [],
  });

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Initial validation on app start
  useEffect(() => {
    const init = async () => {
      try {
        // Get dynamic backend port
        const port = await invoke<number>('get_backend_port');
        console.log('[App] Backend running on port:', port);
        api.setPort(port);

        // Listen for backend logs
        const unlistenStdout = await listen('backend-stdout', (event) => {
          const payload = event.payload as string;
          console.log('[Backend]', payload);
          setState(prev => ({
            ...prev,
            logs: [...prev.logs, payload].slice(-20) // Keep last 20 lines
          }));
        });

        const unlistenStderr = await listen('backend-stderr', (event) => {
          const payload = event.payload as string;
          console.error('[Backend ERROR]', payload);
          setState(prev => ({
            ...prev,
            logs: [...prev.logs, `[ERROR] ${payload}`].slice(-20)
          }));
        });

        performValidation();

        return () => {
          unlistenStdout();
          unlistenStderr();
        };
      } catch (e) {
        console.error('Failed to initialize or get port:', e);
        // Fallback or show error
        performValidation(); // Try anyway? No, api will be on 8000
      }
    };

    init();
  }, []);

  const performValidation = async () => {
    setIsLoading(true);
    setError(null);

    let attempts = 0;
    const maxAttempts = 240; // 240 * 250ms = 60 seconds

    const tryValidation = async () => {
      try {
        const validation = await api.validateSetup();
        setState(prev => ({
          ...prev,
          validationResult: validation,
          isValidated: validation.folders_valid && validation.credentials_valid,
          currentView: validation.folders_valid && validation.credentials_valid ? 'selector' : 'validation',
        }));

        if (validation.folders_valid) {
          const scan = await api.scanFolders();
          setState(prev => ({
            ...prev,
            scanResult: scan,
          }));
        }
        setIsLoading(false);
      } catch (err) {
        attempts++;
        console.log(`[App] Validation attempt ${attempts}/${maxAttempts} failed:`, err);

        if (attempts < maxAttempts) {
          // Retry after 250ms (faster polling for snappier startup)
          setTimeout(tryValidation, 250);
        } else {
          setError(err instanceof Error ? err.message : 'Error de conexión con el servidor. Asegúrate de que el backend esté corriendo.');
          setIsLoading(false);
        }
      }
    };

    await tryValidation();
  };

  const handleClientSelect = (clientName: string) => {
    setState(prev => ({
      ...prev,
      selectedClient: clientName,
    }));
  };

  const handleStartReconciliation = async () => {
    if (!state.selectedClient) return;

    setError(null);
    console.log('[Conciliacion] Starting reconciliation for:', state.selectedClient);

    try {
      // Start reconciliation and get job ID
      console.log('[Conciliacion] Calling API...');
      const { job_id } = await api.startReconciliation(state.selectedClient, state.selectedClient);
      console.log('[Conciliacion] Got job_id:', job_id);

      setState(prev => ({
        ...prev,
        currentJobId: job_id,
        currentView: 'processing',
      }));
    } catch (err) {
      console.error('[Conciliacion] Error:', err);
      const errorMessage = err instanceof Error ? err.message : 'Error al iniciar conciliación';
      setError(errorMessage);
      alert('Error de conexión: ' + errorMessage);
    }
  };

  const handleReconciliationComplete = async () => {
    if (!state.currentJobId) return;

    try {
      const result = await api.getResult(state.currentJobId);
      setState(prev => ({
        ...prev,
        reconciliationResult: result,
        currentView: 'results',
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al obtener resultados');
      setState(prev => ({
        ...prev,
        currentView: 'selector',
      }));
    }
  };

  const handleReconciliationError = (errorMessage: string) => {
    setError(errorMessage);
    setState(prev => ({
      ...prev,
      currentView: 'selector',
    }));
  };

  const handleNavigate = (view: AppView) => {
    setState(prev => ({
      ...prev,
      currentView: view,
    }));
  };

  const handleNewReconciliation = () => {
    setState(prev => ({
      ...prev,
      selectedClient: null,
      reconciliationResult: null,
      currentJobId: null,
      currentView: 'selector',
    }));
  };

  const renderContent = () => {
    if (isLoading) {
      return (
        <div className="loading-container">
          <div className="loading-content">
            <div className="spinner-macos spinner-large" />
            <p className="loading-text">Conectando con el servidor...</p>
            {state.logs.length > 0 && (
              <div style={{ marginTop: 20, fontSize: 10, textAlign: 'left', opacity: 0.7, maxHeight: 100, overflow: 'hidden', fontFamily: 'monospace' }}>
                {state.logs[state.logs.length - 1]}
              </div>
            )}
          </div>
        </div>
      );
    }

    if (error && state.currentView !== 'processing') {
      return (
        <div className="error-container">
          <div className="alert-macos alert-error">
            <svg className="alert-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div className="alert-content">
              <p className="alert-title">Error</p>
              <p className="alert-message">{error}</p>
            </div>
          </div>

          {/* Debug Logs */}
          <div style={{
            marginTop: 20,
            padding: 10,
            background: '#f1f1f1',
            borderRadius: 6,
            width: '100%',
            maxWidth: 500,
            maxHeight: 200,
            overflowY: 'auto',
            fontSize: 11,
            fontFamily: 'monospace',
            border: '1px solid #ddd'
          }}>
            <p style={{ fontWeight: 'bold', marginBottom: 5 }}>Log del Backend:</p>
            {state.logs.length === 0 ? (
              <p style={{ color: '#888' }}>Esperando logs...</p>
            ) : (
              state.logs.map((log, i) => (
                <div key={i} style={{ marginBottom: 2, whiteSpace: 'pre-wrap', color: log.includes('[ERROR]') || log.includes('ERR') ? 'red' : 'inherit' }}>
                  {log}
                </div>
              ))
            )}
          </div>

          <button
            className="btn-macos btn-macos-primary"
            onClick={() => {
              setError(null);
              performValidation();
            }}
            style={{ marginTop: 20 }}
          >
            Reintentar
          </button>
        </div>
      );
    }

    switch (state.currentView) {
      case 'validation':
        return (
          <ValidationScreen
            validationResult={state.validationResult}
            onRetry={performValidation}
            onContinue={() => handleNavigate('selector')}
          />
        );

      case 'selector':
        return (
          <ClientSelector
            scanResult={state.scanResult}
            selectedClient={state.selectedClient}
            onClientSelect={handleClientSelect}
            onStartReconciliation={handleStartReconciliation}
            onRefresh={performValidation}
          />
        );

      case 'processing':
        return (
          <ReconciliationProgress
            clientName={state.selectedClient || ''}
            jobId={state.currentJobId || ''}
            onComplete={handleReconciliationComplete}
            onError={handleReconciliationError}
          />
        );

      case 'results':
        return (
          <ResultsView
            result={state.reconciliationResult}
            clientName={state.selectedClient || ''}
            onNewReconciliation={handleNewReconciliation}
          />
        );

      case 'settings':
        return (
          <SettingsPanel
            onValidate={performValidation}
          />
        );

      default:
        return null;
    }
  };

  return (
    <div className="app-container">
      {/* macOS Titlebar */}
      <div className="titlebar">
        <div className="titlebar-title">Conciliación Financiera</div>
      </div>

      {/* Main Layout */}
      <div className="main-layout">
        <Sidebar
          currentView={state.currentView}
          onNavigate={handleNavigate}
          isValidated={state.isValidated}
          hasResults={state.reconciliationResult !== null}
        />

        <main className="main-content">
          {renderContent()}
        </main>
      </div>
    </div>
  );
}
