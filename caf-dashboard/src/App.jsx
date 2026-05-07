import { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';
import './App.css';

const NODE_URL = 'http://localhost:8000';
const SCALE_FACTOR = 1073741824; // 2^30

// Componente WebGL para renderizar la traza criptográfica
const AttractorCloud = ({ trace }) => {
  const positions = useMemo(() => {
    if (!trace) return new Float32Array();
    const pts = new Float32Array(trace.length * 3);
    trace.forEach((p, i) => {
      // Proyección R4 -> R3 desescalando el punto fijo
      pts[i * 3] = p[0] / SCALE_FACTOR;
      pts[i * 3 + 1] = p[1] / SCALE_FACTOR;
      pts[i * 3 + 2] = p[2] / SCALE_FACTOR;
    });
    return pts;
  }, [trace]);

  if (!trace || trace.length === 0) return null;

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={positions.length / 3}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial size={0.08} color="#00ffcc" transparent opacity={0.9} />
    </points>
  );
};

function App() {
  const [nodeInfo, setNodeInfo] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [selectedTrace, setSelectedTrace] = useState(null);
  const [selectedTxId, setSelectedTxId] = useState(null);

  const fetchData = async () => {
    try {
      const [infoRes, blocksRes] = await Promise.all([
        axios.get(`${NODE_URL}/info`),
        axios.get(`${NODE_URL}/blocks?limit=20`)
      ]);
      setNodeInfo(infoRes.data);
      setBlocks(blocksRes.data);
    } catch (error) {
      console.error("Error conectando con el nodo:", error);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleSelectTx = (tx) => {
    if (tx.signature_data && tx.signature_data.x_final) {
      setSelectedTrace(tx.signature_data.x_final);
      setSelectedTxId(tx.tx_id);
    } else {
      alert("Esta transacción no contiene una traza topológica (ej. Coinbase).");
    }
  };

  return (
    <div className="dashboard-container">
      {/* Panel Izquierdo: Explorador de Bloques */}
      <div className="panel-left">
        <div className="header">
          <h2>CAF Protocol Node</h2>
          <p>Estado de la Red P2P y Telemetría</p>
        </div>

        {nodeInfo && (
          <div className="card">
            <strong>Altura del Ledger:</strong> {nodeInfo.chain_length} bloques<br />
            <strong>TXs en Mempool:</strong> {nodeInfo.mempool_size}<br />
            <strong>Último Hash:</strong> {nodeInfo.latest_block_hash.substring(0, 16)}...
          </div>
        )}

        <h3>Libro Mayor Inmutable</h3>
        {blocks.map((block) => (
          <div key={block.hash} className="block-item">
            <strong>Bloque #{block.index}</strong>
            <div>Hash: {block.hash.substring(0, 16)}...</div>
            <div>Transacciones: {block.transactions.length}</div>
            
            {block.transactions.map(tx => (
              <div key={tx.tx_id} className="tx-item" onClick={() => handleSelectTx(tx)}>
                <div>ID: {tx.tx_id.substring(0, 16)}...</div>
                <div>Monto: {(tx.amount / SCALE_FACTOR).toFixed(2)} CAF</div>
                {tx.signature_data?.x_final && (
                  <button className="btn-view">Ver Atractor ZK</button>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Panel Derecho: Motor de Renderizado 3D */}
      <div className="panel-right">
        {selectedTxId && (
          <div className="canvas-overlay">
            <strong>Auditoría Visual ZK-STARK</strong><br/>
            TX: {selectedTxId.substring(0, 16)}...<br/>
            Puntos renderizados: {selectedTrace?.length || 0}
          </div>
        )}
        <Canvas camera={{ position: [2, 2, 3], fov: 60 }}>
          <color attach="background" args={['#000000']} />
          <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade speed={1} />
          <ambientLight intensity={0.5} />
          <OrbitControls autoRotate autoRotateSpeed={2.0} enablePan={true} enableZoom={true} />
          {/* Ejes de referencia en el centro (0,0,0) */}
          <axesHelper args={[2]} />
          
          <AttractorCloud trace={selectedTrace} />
        </Canvas>
      </div>
    </div>
  );
}

export default App;
