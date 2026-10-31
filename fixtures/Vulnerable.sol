// SPDX-License-Identifier: MIT
pragma solidity 0.8.20;

// Intentionally vulnerable test fixture. Do not deploy.
contract Vault {
    mapping(address => uint256) public balances;
    address public owner;

    constructor() { owner = msg.sender; }

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    // Reentrancy: external call before state update.
    function withdraw() external {
        uint256 amount = balances[msg.sender];
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok);
        balances[msg.sender] = 0;
    }

    // Unprotected: anyone can drain.
    function setOwner(address newOwner) external {
        owner = newOwner;
    }

    // tx.origin auth.
    function emergencyWithdraw(address to) external {
        require(tx.origin == owner);
        payable(to).transfer(address(this).balance);
    }
}
