/**
 * Document Ingestion & Library Module
 * Modular Facade orchestrating list rendering, upload progress, audit trail and deletion.
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.documents = RAG.documents || {};

  function initDocuments() {
    if (RAG.documents.initDropzoneEvents) RAG.documents.initDropzoneEvents();
    if (RAG.documents.initAuditModalEvents) RAG.documents.initAuditModalEvents();
  }

  RAG.documents.init = initDocuments;

  // Bind top-level global handlers for inline DOM event triggers
  global.loadDocuments = (force) => RAG.documents.loadDocuments && RAG.documents.loadDocuments(force);
  global.deleteDoc = (id, ev) => RAG.documents.deleteDoc && RAG.documents.deleteDoc(id, ev);
  global.reprocessDoc = (id) => RAG.documents.reprocessDoc && RAG.documents.reprocessDoc(id);
  global.showDocAudit = (id) => RAG.documents.showDocAudit && RAG.documents.showDocAudit(id);
  global.toggleDocShare = (id, shared) => RAG.documents.toggleDocShare && RAG.documents.toggleDocShare(id, shared);
  global.retryLoadDocs = () => RAG.documents.loadDocuments && RAG.documents.loadDocuments(true);
})(window);
