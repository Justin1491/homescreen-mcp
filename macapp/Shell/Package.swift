// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Homescreen",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "Homescreen", path: "Sources/Homescreen")
    ]
)
