// SPDX-License-Identifier: MIT
pragma solidity 0.8.20;

// Intentionally dangerous test fixture for Warden demos. Do not send real funds.
contract Drainer {
    receive() external payable {}

    function kill() external {
        selfdestruct(payable(msg.sender));
    }
}
