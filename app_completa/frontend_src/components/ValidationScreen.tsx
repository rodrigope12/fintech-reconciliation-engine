import { FC } from 'react';
import { ValidationResult } from '../services/desktopApi';

interface ValidationScreenProps {
  validationResult: ValidationResult | null;
  onRetry: () => void;
  onContinue: () => void;
}

export const ValidationScreen: FC<ValidationScreenProps> = ({
  validationResult,
  onRetry,
  onContinue,
}) => {
  if (!validationResult) {
    return (
      <div className="validation-screen">
        <div className="validation-loading">
          <div className="spinner-macos spinner-large" />
          <p>Verificando configuración...</p>
        </div>
      </div>
    );
  }

  const allValid = validationResult.folders_valid && validationResult.credentials_valid;

  return (
    <div className="validation-screen animate-fade-in">
      <div className="validation-header">
        <div className={`validation-icon ${allValid ? 'validation-icon-success' : 'validation-icon-warning'}`}>
          {allValid ? (
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          )}
        </div>
        <h1 className="validation-title">
          {allValid ? 'Sistema Configurado' : 'Configuración Requerida'}
        </h1>
        <p className="validation-subtitle">
          {allValid
            ? 'Todos los componentes están listos para usar'
            : 'Algunos componentes necesitan configuración'}
        </p>
      </div>

      <div className="validation-sections">
        {/* Folders Section */}
        <div className="grouped-section">
          <h3 className="grouped-section-header">Carpetas de Trabajo</h3>

          <div className="grouped-item">
            <div className="validation-item-content">
              <div className={`icon-circle ${validationResult.folders_valid ? 'icon-circle-green' : 'icon-circle-orange'}`}>
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
              </div>
              <div className="validation-item-text">
                <span className="validation-item-label">Carpeta PDF</span>
                <span className="validation-item-path">{validationResult.pdf_folder_path}</span>
              </div>
            </div>
            <span className={`badge ${validationResult.folders_valid ? 'badge-success' : 'badge-warning'}`}>
              {validationResult.folders_valid ? 'OK' : 'No encontrada'}
            </span>
          </div>

          <div className="grouped-item">
            <div className="validation-item-content">
              <div className={`icon-circle ${validationResult.folders_valid ? 'icon-circle-green' : 'icon-circle-orange'}`}>
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <div className="validation-item-text">
                <span className="validation-item-label">Carpeta CFDI</span>
                <span className="validation-item-path">{validationResult.cfdi_folder_path}</span>
              </div>
            </div>
            <span className={`badge ${validationResult.folders_valid ? 'badge-success' : 'badge-warning'}`}>
              {validationResult.folders_valid ? 'OK' : 'No encontrada'}
            </span>
          </div>

          {validationResult.folder_errors.length > 0 && (
            <div className="validation-errors">
              {validationResult.folder_errors.map((error, index) => (
                <p key={index} className="validation-error-text">{error}</p>
              ))}
            </div>
          )}
        </div>

        {/* Credentials Section */}
        <div className="grouped-section">
          <h3 className="grouped-section-header">Credenciales API</h3>

          <div className="grouped-item">
            <div className="validation-item-content">
              <div className={`icon-circle ${validationResult.credentials_valid ? 'icon-circle-green' : 'icon-circle-orange'}`}>
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                </svg>
              </div>
              <div className="validation-item-text">
                <span className="validation-item-label">Google Cloud Vision</span>
                <span className="validation-item-path">{validationResult.credentials_path}</span>
              </div>
            </div>
            <span className={`badge ${validationResult.credentials_valid ? 'badge-success' : 'badge-error'}`}>
              {validationResult.credentials_valid ? 'Válido' : 'Inválido'}
            </span>
          </div>

          <div className="validation-message-box">
            <p className={validationResult.credentials_valid ? 'text-success' : 'text-warning'}>
              {validationResult.credentials_message}
            </p>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="validation-actions">
        {!allValid && (
          <button className="btn-macos btn-macos-secondary" onClick={onRetry}>
            <svg className="btn-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Verificar de nuevo
          </button>
        )}
        <button
          className="btn-macos btn-macos-primary btn-macos-large"
          onClick={onContinue}
          disabled={!allValid}
        >
          {allValid ? 'Comenzar' : 'Configure primero'}
          {allValid && (
            <svg className="btn-icon-right" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          )}
        </button>
      </div>

      {/* Help Text */}
      {!allValid && (
        <div className="validation-help">
          <h4>Para configurar el sistema:</h4>
          <ol>
            <li>Cree las carpetas <code>pdf</code> y <code>CFDI</code> en el directorio de trabajo</li>
            <li>Agregue subcarpetas con el nombre de cada cliente</li>
            <li>Coloque el archivo <code>clave_API_cloud_vision.json</code> en la carpeta de la aplicación</li>
          </ol>
        </div>
      )}
    </div>
  );
};
