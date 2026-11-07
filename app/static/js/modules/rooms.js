/**
 * Room Workspaces & Multi-File Scoping
 * Modular Facade orchestrating list rendering, member access (RBAC), and CRUD actions.
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.rooms = RAG.rooms || {};

  // Bind top-level global handlers for inline DOM event triggers
  global.loadRooms = () => RAG.rooms.loadRooms && RAG.rooms.loadRooms();
  global.selectRoom = (id, switchTab) => RAG.rooms.selectRoom && RAG.rooms.selectRoom(id, switchTab);
  global.deleteRoom = (id, ev) => RAG.rooms.deleteRoom && RAG.rooms.deleteRoom(id, ev);
  global.detachDocFromRoom = (roomId, docId, ev) => RAG.rooms.detachDocFromRoom && RAG.rooms.detachDocFromRoom(roomId, docId, ev);
  global.openShareRoomModal = (id) => RAG.rooms.openShareRoomModal && RAG.rooms.openShareRoomModal(id);
  global.removeRoomMember = (roomId, userId) => RAG.rooms.removeRoomMember && RAG.rooms.removeRoomMember(roomId, userId);
})(window);
