// SPDX-License-Identifier: MIT
pragma solidity 0.8.20;

// Intentionally risky test fixture for Warden demos. An EIP-1967 style proxy: whoever is admin can
// swap the logic behind this address at any time. Do not send it real funds.
contract UpgradeableProxy {
    address public admin;

    constructor() {
        admin = msg.sender;
        // EIP-1967 implementation slot, pointed at a dummy address
        assembly {
            sstore(0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc,
                   0x000000000000000000000000000000000000dEaD)
        }
    }

    function upgradeTo(address newImplementation) external {
        require(msg.sender == admin, "not admin");
        assembly {
            sstore(0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc, newImplementation)
        }
    }

    fallback() external payable {
        assembly {
            let impl := sload(0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc)
            calldatacopy(0, 0, calldatasize())
            let ok := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch ok
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    receive() external payable {}
}
