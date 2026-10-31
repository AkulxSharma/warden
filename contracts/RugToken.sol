// SPDX-License-Identifier: MIT
pragma solidity 0.8.20;

// Intentionally risky test fixture for Warden demos. Owner-only mint, pause and blacklist are
// classic rug-pull powers. Do not send it real funds.
contract RugToken {
    string public name = "RugToken";
    string public symbol = "RUG";
    uint8 public decimals = 18;
    uint256 public totalSupply;
    address public owner;
    bool public paused;
    mapping(address => uint256) public balanceOf;
    mapping(address => bool) public blacklisted;

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    function mint(address to, uint256 amount) external onlyOwner {
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function pause() external onlyOwner {
        paused = true;
    }

    function unpause() external onlyOwner {
        paused = false;
    }

    function blacklist(address account) external onlyOwner {
        blacklisted[account] = true;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        owner = newOwner;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(!paused && !blacklisted[msg.sender], "transfers blocked");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}
