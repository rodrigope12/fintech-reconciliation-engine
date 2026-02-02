import { FC, useState, useEffect } from 'react';
import { api } from '../services/desktopApi';

interface SettingsPanelProps {
  onValidate: () => void;
}

export const SettingsPanel: FC<SettingsPanelProps> = ({ onValidate }) => {
  const [basePath, setBasePath] = useState('/Users/usuario/Documents/conciliacion');
  const [pdfFolderName, setPdfFolderName] = useState('pdf');
  const [cfdiFolderName, setCfdiFolderName] = useState('CFDI');
  const [credentialsPath, setCredentialsPath] = useState('./clave_API_cloud_vision.json');

  // Solver Settings State - using strings to allow controlled input (e.g. empty string)
  const [maxAbsDelta, setMaxAbsDelta] = useState('50');
  const [relDeltaRatio, setRelDeltaRatio] = useState('0.1');
  const [solverTimeout, setSolverTimeout] = useState('30');
  const [maxClusterSize, setMaxClusterSize] = useState('100');

  // Load actual backend settings on mount
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const current = await api.getSettings();
        if (current.max_abs_delta_cents !== undefined) setMaxAbsDelta(String(current.max_abs_delta_cents));
        if (current.rel_delta_ratio !== undefined) setRelDeltaRatio(String(current.rel_delta_ratio));
        if (current.solver_timeout_seconds !== undefined) setSolverTimeout(String(current.solver_timeout_seconds));
        if (current.max_cluster_size !== undefined) setMaxClusterSize(String(current.max_cluster_size));
        if (current.google_application_credentials) setCredentialsPath(current.google_application_credentials);
      } catch (error) {
        console.error("Failed to load backend settings:", error);
      }
    };
    loadSettings();
  }, []);

  const handleSave = async () => {
    // Save to local storage for persistence across reloads (frontend cache)
    localStorage.setItem('settings', JSON.stringify({
      basePath,
      pdfFolderName,
      cfdiFolderName,
      credentialsPath,
    }));

    // Send backend configuration updates
    try {
      await api.updateSettings({
        max_abs_delta_cents: Number(maxAbsDelta),
        rel_delta_ratio: Number(relDeltaRatio),
        solver_timeout_seconds: Number(solverTimeout),
        max_cluster_size: Number(maxClusterSize),
        // google_application_credentials: credentialsPath // Optional, if needed
      });

      // Mensaje exacto solicitado por el usuario
      alert("Configuración guardada. Por favor reinicia la aplicación para aplicar los cambios.");
      onValidate(); // Trigger validation/refresh

    } catch (error) {
      console.error('Error saving settings:', error);
      alert('Error de conexión con el servidor. Asegúrese de que la aplicación esté corriendo.');
    }
  };

  const handleBrowse = (field: 'basePath' | 'credentialsPath') => {
    // In Tauri, this would open a file dialog
    console.log('Browse for:', field);
  };

  return (
    <div className="settings-panel animate-fade-in">
      <div className="settings-header">
        <h1 className="settings-title">Ajustes</h1>
        <p className="settings-subtitle">Configure las rutas y credenciales del sistema</p>
      </div>

      {/* Folder Settings */}
      <div className="grouped-section">
        <h3 className="grouped-section-header">Carpetas de Trabajo</h3>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Directorio Base</span>
            <span className="settings-description">Carpeta principal donde se encuentran los archivos</span>
          </div>
          <div className="settings-item-control">
            <input
              type="text"
              className="input-macos"
              value={basePath}
              onChange={(e) => setBasePath(e.target.value)}
            />
            <button
              className="btn-macos btn-macos-secondary btn-small"
              onClick={() => handleBrowse('basePath')}
            >
              Examinar...
            </button>
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Nombre Carpeta PDF</span>
            <span className="settings-description">Subcarpeta con estados de cuenta</span>
          </div>
          <div className="settings-item-control">
            <input
              type="text"
              className="input-macos input-small"
              value={pdfFolderName}
              onChange={(e) => setPdfFolderName(e.target.value)}
            />
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Nombre Carpeta CFDI</span>
            <span className="settings-description">Subcarpeta con facturas electrónicas</span>
          </div>
          <div className="settings-item-control">
            <input
              type="text"
              className="input-macos input-small"
              value={cfdiFolderName}
              onChange={(e) => setCfdiFolderName(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* API Credentials */}
      <div className="grouped-section">
        <h3 className="grouped-section-header">Credenciales API</h3>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Google Cloud Vision</span>
            <span className="settings-description">Archivo JSON con credenciales de servicio</span>
          </div>
          <div className="settings-item-control">
            <input
              type="text"
              className="input-macos"
              value={credentialsPath}
              onChange={(e) => setCredentialsPath(e.target.value)}
            />
            <button
              className="btn-macos btn-macos-secondary btn-small"
              onClick={() => handleBrowse('credentialsPath')}
            >
              Examinar...
            </button>
          </div>
        </div>

        <div className="settings-info">
          <svg className="info-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div className="info-content">
            <p className="info-title">Obtener credenciales de Google Cloud Vision</p>
            <ol className="info-steps">
              <li>Acceda a <code>console.cloud.google.com</code></li>
              <li>Cree o seleccione un proyecto</li>
              <li>Habilite la API de Cloud Vision</li>
              <li>Cree una cuenta de servicio con permisos</li>
              <li>Descargue el archivo JSON de credenciales</li>
            </ol>
          </div>
        </div>
      </div>

      {/* Solver Settings */}
      <div className="grouped-section">
        <h3 className="grouped-section-header">Parámetros del Solver</h3>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Tolerancia Absoluta</span>
            <span className="settings-description">Máximo error permitido en centavos</span>
          </div>
          <div className="settings-item-control">
            <input
              type="number"
              className="input-macos input-small"
              value={maxAbsDelta}
              onChange={(e) => setMaxAbsDelta(e.target.value)}
              min={0}
              max={1000}
            />
            <span className="input-suffix">centavos</span>
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Tolerancia Relativa</span>
            <span className="settings-description">Porcentaje máximo de error</span>
          </div>
          <div className="settings-item-control">
            <input
              type="number"
              className="input-macos input-small"
              value={relDeltaRatio}
              onChange={(e) => setRelDeltaRatio(e.target.value)}
              min={0}
              max={1}
              step={0.01}
            />
            <span className="input-suffix">%</span>
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Timeout del Solver</span>
            <span className="settings-description">Tiempo máximo por cluster</span>
          </div>
          <div className="settings-item-control">
            <input
              type="number"
              className="input-macos input-small"
              value={solverTimeout}
              onChange={(e) => setSolverTimeout(e.target.value)}
              min={5}
              max={300}
            />
            <span className="input-suffix">segundos</span>
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-item-label">
            <span className="settings-label">Tamaño Máximo de Cluster</span>
            <span className="settings-description">Límite antes de subdividir</span>
          </div>
          <div className="settings-item-control">
            <input
              type="number"
              className="input-macos input-small"
              value={maxClusterSize}
              onChange={(e) => setMaxClusterSize(e.target.value)}
              min={10}
              max={500}
            />
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="settings-actions">
        <button className="btn-macos btn-macos-secondary" onClick={onValidate}>
          Verificar Configuración
        </button>
        <button className="btn-macos btn-macos-primary" onClick={handleSave}>
          Guardar Cambios
        </button>
      </div>

      {/* About */}
      <div className="settings-about">
        <div className="about-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
          </svg>
        </div>
        <div className="about-info">
          <p className="about-name">Conciliación Financiera</p>
          <p className="about-version">Versión 1.0.0</p>
          <p className="about-description">
            Sistema de conciliación automatizada con OCR y optimización MILP.
            Optimizado para Apple Silicon.
          </p>
        </div>
      </div>
    </div>
  );
};
