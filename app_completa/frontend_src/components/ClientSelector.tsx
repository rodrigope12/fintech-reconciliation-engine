import { FC, useState, useMemo } from 'react';
import { ScanResult } from '../services/desktopApi';

interface ClientSelectorProps {
  scanResult: ScanResult | null;
  selectedClient: string | null;
  onClientSelect: (clientName: string) => void;
  onStartReconciliation: () => void;
  onRefresh: () => void;
}

export const ClientSelector: FC<ClientSelectorProps> = ({
  scanResult,
  selectedClient,
  onClientSelect,
  onStartReconciliation,
  onRefresh,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<'all' | 'matched' | 'pdf_only' | 'cfdi_only'>('all');

  // Get all unique clients
  const allClients = useMemo(() => {
    if (!scanResult) return [];

    const clientMap = new Map<string, {
      name: string;
      hasPdf: boolean;
      hasCfdi: boolean;
      pdfCount: number;
      cfdiCount: number;
      pdfSize: number;
      cfdiSize: number;
    }>();

    scanResult.pdf_clients.forEach(client => {
      clientMap.set(client.name.toLowerCase(), {
        name: client.name,
        hasPdf: true,
        hasCfdi: false,
        pdfCount: client.file_count,
        cfdiCount: 0,
        pdfSize: client.size_mb,
        cfdiSize: 0,
      });
    });

    scanResult.cfdi_clients.forEach(client => {
      const existing = clientMap.get(client.name.toLowerCase());
      if (existing) {
        existing.hasCfdi = true;
        existing.cfdiCount = client.file_count;
        existing.cfdiSize = client.size_mb;
      } else {
        clientMap.set(client.name.toLowerCase(), {
          name: client.name,
          hasPdf: false,
          hasCfdi: true,
          pdfCount: 0,
          cfdiCount: client.file_count,
          pdfSize: 0,
          cfdiSize: client.size_mb,
        });
      }
    });

    return Array.from(clientMap.values()).sort((a, b) =>
      a.name.localeCompare(b.name, 'es', { sensitivity: 'base' })
    );
  }, [scanResult]);

  // Filter clients
  const filteredClients = useMemo(() => {
    let clients = allClients;

    // Apply type filter
    switch (filterType) {
      case 'matched':
        clients = clients.filter(c => c.hasPdf && c.hasCfdi);
        break;
      case 'pdf_only':
        clients = clients.filter(c => c.hasPdf && !c.hasCfdi);
        break;
      case 'cfdi_only':
        clients = clients.filter(c => !c.hasPdf && c.hasCfdi);
        break;
    }

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      clients = clients.filter(c => c.name.toLowerCase().includes(query));
    }

    return clients;
  }, [allClients, filterType, searchQuery]);

  const selectedClientData = useMemo(() => {
    if (!selectedClient) return null;
    return allClients.find(c => c.name === selectedClient) || null;
  }, [allClients, selectedClient]);

  const stats = useMemo(() => ({
    total: allClients.length,
    matched: allClients.filter(c => c.hasPdf && c.hasCfdi).length,
    pdfOnly: allClients.filter(c => c.hasPdf && !c.hasCfdi).length,
    cfdiOnly: allClients.filter(c => !c.hasPdf && c.hasCfdi).length,
  }), [allClients]);

  return (
    <div className="client-selector animate-fade-in">
      {/* Header */}
      <div className="selector-header">
        <div className="selector-title-row">
          <h1 className="selector-title">Seleccionar Cliente</h1>
          <button className="btn-macos btn-macos-secondary btn-icon-only" onClick={onRefresh} title="Actualizar">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
        <p className="selector-subtitle">
          Seleccione el cliente para iniciar la conciliación
        </p>
      </div>

      {/* Stats Cards */}
      <div className="stats-grid">
        <div className="card-macos stat-card">
          <div className="stat-value">{stats.total}</div>
          <div className="stat-label">Total Clientes</div>
        </div>
        <div className="card-macos stat-card">
          <div className="stat-value stat-value-success">{stats.matched}</div>
          <div className="stat-label">Listos</div>
        </div>
        <div className="card-macos stat-card">
          <div className="stat-value stat-value-warning">{stats.pdfOnly}</div>
          <div className="stat-label">Solo PDF</div>
        </div>
        <div className="card-macos stat-card">
          <div className="stat-value stat-value-warning">{stats.cfdiOnly}</div>
          <div className="stat-label">Solo CFDI</div>
        </div>
      </div>

      {/* Search and Filter */}
      <div className="selector-controls">
        <div className="search-box">
          <svg className="search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            className="search-input"
            placeholder="Buscar cliente..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button className="search-clear" onClick={() => setSearchQuery('')}>
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        <div className="filter-tabs">
          <button
            className={`filter-tab ${filterType === 'all' ? 'filter-tab-active' : ''}`}
            onClick={() => setFilterType('all')}
          >
            Todos
          </button>
          <button
            className={`filter-tab ${filterType === 'matched' ? 'filter-tab-active' : ''}`}
            onClick={() => setFilterType('matched')}
          >
            Listos
          </button>
          <button
            className={`filter-tab ${filterType === 'pdf_only' ? 'filter-tab-active' : ''}`}
            onClick={() => setFilterType('pdf_only')}
          >
            Solo PDF
          </button>
          <button
            className={`filter-tab ${filterType === 'cfdi_only' ? 'filter-tab-active' : ''}`}
            onClick={() => setFilterType('cfdi_only')}
          >
            Solo CFDI
          </button>
        </div>
      </div>

      {/* Client List */}
      <div className="client-list-container">
        <div className="grouped-section">
          {filteredClients.length === 0 ? (
            <div className="empty-state">
              <svg className="empty-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
              <p>No se encontraron clientes</p>
            </div>
          ) : (
            filteredClients.map((client) => (
              <button
                key={client.name}
                className={`client-item ${selectedClient === client.name ? 'client-item-selected' : ''} ${!client.hasPdf || !client.hasCfdi ? 'client-item-incomplete' : ''}`}
                onClick={() => onClientSelect(client.name)}
              >
                <div className="client-item-main">
                  <div className={`client-icon ${client.hasPdf && client.hasCfdi ? 'client-icon-ready' : 'client-icon-pending'}`}>
                    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                    </svg>
                  </div>
                  <div className="client-info">
                    <span className="client-name">{client.name}</span>
                    <div className="client-details">
                      <span className={`client-badge ${client.hasPdf ? 'badge-success' : 'badge-warning'}`}>
                        {client.pdfCount} PDFs
                      </span>
                      <span className={`client-badge ${client.hasCfdi ? 'badge-success' : 'badge-warning'}`}>
                        {client.cfdiCount} CFDIs
                      </span>
                    </div>
                  </div>
                </div>
                <div className="client-item-status">
                  {client.hasPdf && client.hasCfdi ? (
                    <span className="badge badge-success">Listo</span>
                  ) : (
                    <span className="badge badge-warning">Incompleto</span>
                  )}
                  <svg className="chevron-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Selected Client Panel */}
      {selectedClientData && (
        <div className="selected-panel">
          <div className="selected-info">
            <h3 className="selected-name">{selectedClientData.name}</h3>
            <div className="selected-stats">
              <span>{selectedClientData.pdfCount} estados de cuenta</span>
              <span className="separator">•</span>
              <span>{selectedClientData.cfdiCount} facturas</span>
              <span className="separator">•</span>
              <span>{(selectedClientData.pdfSize + selectedClientData.cfdiSize).toFixed(1)} MB</span>
            </div>
          </div>
          <button
            className="btn-macos btn-macos-primary btn-macos-large"
            onClick={onStartReconciliation}
            disabled={!selectedClientData.hasPdf || !selectedClientData.hasCfdi}
          >
            Iniciar Conciliación
            <svg className="btn-icon-right" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </button>
        </div>
      )}

      {/* Warnings */}
      {scanResult && scanResult.warnings.length > 0 && (
        <div className="warnings-panel">
          <h4 className="warnings-title">
            <svg className="warning-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            Avisos ({scanResult.warnings.length})
          </h4>
          <ul className="warnings-list">
            {scanResult.warnings.slice(0, 5).map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
            {scanResult.warnings.length > 5 && (
              <li className="more-warnings">Y {scanResult.warnings.length - 5} más...</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
};
