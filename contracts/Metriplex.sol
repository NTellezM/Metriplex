// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title  Metriplex (MPX)
 * @notice Token ERC-20 — primera blockchain con identidad fractal.
 *         Puente bidireccional Metriplex ↔ Ethereum.
 * @dev    Tagline: "Order from chaos" | https://metriplex.io
 */
contract Metriplex is ERC20, Ownable {

    uint256 public constant MAX_SUPPLY = 21_000_000 * 10**18;
    bool    public initialized = false;

    event BridgeBurn(
        address indexed from,
        string          nativeRecipient,
        uint256         amount
    );

    constructor(address relayer)
        ERC20("Metriplex", "MPX")
        Ownable(relayer)
    {}

    // Llamar UNA SOLA VEZ tras el deploy
    function initialize(address liquidityWallet) external onlyOwner {
        require(!initialized, "Ya inicializado");
        initialized = true;
        _mint(liquidityWallet,  8_400_000 * 10**18);  // 40% Uniswap
        _mint(owner(),         12_600_000 * 10**18);  // 60% bóveda + equipo
    }

    // Solo el relayer puede emitir (Nativo → Ethereum)
    function mint(address to, uint256 amount) external onlyOwner {
        require(totalSupply() + amount <= MAX_SUPPLY, "Supply maximo");
        _mint(to, amount);
    }

    // Cualquier usuario puede quemar (Ethereum → Nativo)
    function burnForNative(uint256 amount, string calldata nativeRecipient) external {
        require(balanceOf(msg.sender) >= amount, "Saldo insuficiente");
        _burn(msg.sender, amount);
        emit BridgeBurn(msg.sender, nativeRecipient, amount);
    }
}
