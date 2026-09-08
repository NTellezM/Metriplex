// SPDX-License-Identifier: MIT
/**
 * @notice DEPRECATED — este es el contrato desplegado en Sepolia testnet.
 *         Para el lanzamiento en mainnet, usa contracts/Metriplex.sol
 *         Sepolia address: 0x22D3f414438556d1B071cCfE52513d4d829400fd
 */
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract WrappedMetriplex is ERC20, Ownable {
    
    // Evento vital: El servidor Python escuchará esto para liberar MPX nativos
    event BridgeBurn(address indexed from, string nativeRecipient, uint256 amount);

    // El "Owner" será la dirección (billetera) de tu servidor Relayer en Python
    constructor(address initialRelayer) 
        ERC20("Wrapped Metriplex", "wMPX") 
        Ownable(initialRelayer) 
    {}

    /**
     * @dev FLUJO DE ENTRADA (Nativo -> Ethereum):
     * Solo el Relayer de Python puede ejecutar esta función.
     * Se invoca cuando el script detecta que alguien bloqueó MPX en tu blockchain nativa.
     */
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    /**
     * @dev FLUJO DE SALIDA (Ethereum -> Nativo):
     * Cualquier usuario puede ejecutar esta función desde Metamask.
     * Quema los wMPX en Ethereum y avisa al Relayer a qué billetera nativa enviarlos.
     */
    function burnForNative(uint256 amount, string calldata nativeRecipient) external {
        require(balanceOf(msg.sender) >= amount, "Saldo wMPX insuficiente");
        
        // 1. Destruimos los tokens en la red externa
        _burn(msg.sender, amount);
        
        // 2. Gritamos al vacío de la blockchain. El script de Python lo escuchará.
        emit BridgeBurn(msg.sender, nativeRecipient, amount);
    }
}