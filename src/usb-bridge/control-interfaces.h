/* Minimal C ABI declarations for SDK-used interfaces missing from these Wine
 * headers. Method order/GUIDs verified against upstream mingw-w64 vidcap.h,
 * ksproxy.h and ksmedia.h. Reference copies are not distributed here;
 * see NOTICE.md and docs/PROVENANCE.md for provenance and upstream notices. */
#include <strmif.h>
#define CameraControl_Exposure 4
typedef struct BridgeTopology BridgeTopology;
typedef struct BridgeKs BridgeKs;
typedef struct { GUID Set; ULONG Id, Flags; } BridgeProperty;
typedef struct { BridgeProperty Property; ULONG NodeId, Reserved; } BridgeNode;
typedef struct { ULONG FromNode, FromNodePin, ToNode, ToNodePin; } BridgeConnection;
typedef struct {
 HRESULT (WINAPI *QueryInterface)(BridgeTopology *, REFIID, void **);
 ULONG (WINAPI *AddRef)(BridgeTopology *);
 ULONG (WINAPI *Release)(BridgeTopology *);
 HRESULT (WINAPI *NumCategories)(BridgeTopology *, DWORD *);
 HRESULT (WINAPI *Category)(BridgeTopology *, DWORD, GUID *);
 HRESULT (WINAPI *NumConnections)(BridgeTopology *, DWORD *);
 HRESULT (WINAPI *Connection)(BridgeTopology *, DWORD, BridgeConnection *);
 HRESULT (WINAPI *NodeName)(BridgeTopology *, DWORD, WCHAR *, DWORD, DWORD *);
 HRESULT (WINAPI *NumNodes)(BridgeTopology *, DWORD *);
 HRESULT (WINAPI *NodeType)(BridgeTopology *, DWORD, GUID *);
 HRESULT (WINAPI *CreateNode)(BridgeTopology *, DWORD, REFIID, void **);
} BridgeTopologyVtbl;
struct BridgeTopology { const BridgeTopologyVtbl *lpVtbl; };
typedef struct {
 HRESULT (WINAPI *QueryInterface)(BridgeKs *, REFIID, void **);
 ULONG (WINAPI *AddRef)(BridgeKs *);
 ULONG (WINAPI *Release)(BridgeKs *);
 HRESULT (WINAPI *Property)(BridgeKs *, BridgeProperty *, ULONG, void *, ULONG, ULONG *);
 HRESULT (WINAPI *Method)(BridgeKs *, void *, ULONG, void *, ULONG, ULONG *);
 HRESULT (WINAPI *Event)(BridgeKs *, void *, ULONG, void *, ULONG, ULONG *);
} BridgeKsVtbl;
struct BridgeKs { const BridgeKsVtbl *lpVtbl; };
static const GUID bridge_iid_topology = {0x720d4ac0,0x7533,0x11d0,{0xa5,0xd6,0x28,0xdb,0x04,0xc1,0,0}};
static const GUID bridge_iid_ks = {0x28f54685,0x06fd,0x11d2,{0xb2,0x7a,0,0xa0,0xc9,0x22,0x31,0x96}};
static const GUID bridge_node_type = {0x941c7ac0,0xc559,0x11d0,{0x8a,0x2b,0,0xa0,0xc9,0x25,0x5a,0xc1}};
static const GUID bridge_xu_guid = {0xa55751a1,0xf3c5,0x4a5e,{0x8d,0x5a,0x68,0x54,0xb8,0xfa,0x27,0x16}};
