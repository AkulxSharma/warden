// SPDX-License-Identifier: MIT
pragma solidity 0.8.20;

// Intentionally risky test fixture for Warden demos. It authorizes with tx.origin, so any contract
// the owner is tricked into calling can drain it. Do not send it real funds.
contract Phisher {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    receive() external payable {}

    function withdrawAll(address payable to) external {
        require(tx.origin == owner, "not owner");
        to.transfer(address(this).balance);
    }
}
