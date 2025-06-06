from conan import ConanFile
from conan.tools.apple import is_apple_os
from conan.tools.build import stdcpp_library
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.env import VirtualBuildEnv
from conan.tools.files import apply_conandata_patches, export_conandata_patches, get, copy, rmdir, replace_in_file, collect_libs, rm, rename
from conan.tools.microsoft import is_msvc
from conan.tools.scm import Version
import os

required_conan_version = ">=1.60.0 <2 || >=2.0.5"


class ProjConan(ConanFile):
    name = "proj"
    description = "Cartographic Projections and Coordinate Transformations Library."
    license = "MIT"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://proj.org"
    topics = ("dsp", "proj", "proj4", "projections", "gis", "geospatial")
    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
        "threadsafe": [True, False],
        "with_tiff": [True, False],
        "with_curl": [True, False],
        "build_executables": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
        "threadsafe": True,
        "with_tiff": True,
        "with_curl": True,
        "build_executables": True,
    }

    def export_sources(self):
        export_conandata_patches(self)

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC
        if Version(self.version) < "7.0.0":
            del self.options.with_tiff
            del self.options.with_curl

    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")

    def layout(self):
        cmake_layout(self, src_folder="src")

    def requirements(self):
        self.requires("nlohmann_json/3.11.3")
        self.requires("sqlite3/[>=3.44 <4]")
        if self.options.get_safe("with_tiff"):
            self.requires("libtiff/4.6.0")
        if self.options.get_safe("with_curl"):
            self.requires("libcurl/[>=7.78.0 <9]")

    def build_requirements(self):
        if Version(self.version) >= "9.4.0":
            self.tool_requires("cmake/[>=3.16 <4]")

        self.tool_requires("sqlite3/<host_version>")

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)

    def generate(self):
        env = VirtualBuildEnv(self)
        env.generate()

        tc = CMakeToolchain(self)
        tc.variables["USE_THREAD"] = self.options.threadsafe
        tc.variables["BUILD_CCT"] = self.options.build_executables
        tc.variables["BUILD_CS2CS"] = self.options.build_executables
        tc.variables["BUILD_GEOD"] = self.options.build_executables
        tc.variables["BUILD_GIE"] = self.options.build_executables
        tc.variables["BUILD_PROJ"] = self.options.build_executables
        tc.variables["BUILD_PROJINFO"] = self.options.build_executables
        if Version(self.version) < "9.1.0":
            tc.variables["PROJ_DATA_SUBDIR"] = "res"
        if Version(self.version) < "7.0.0":
            tc.variables["PROJ_TESTS"] = False
            tc.variables["BUILD_LIBPROJ_SHARED"] = self.options.shared
            tc.variables["ENABLE_LTO"] = False
            tc.variables["JNI_SUPPORT"] = False
        else:
            tc.variables["ENABLE_TIFF"] = self.options.with_tiff
            tc.variables["ENABLE_CURL"] = self.options.with_curl
            tc.variables["BUILD_TESTING"] = False
            tc.variables["ENABLE_IPO"] = False
            tc.variables["BUILD_PROJSYNC"] = self.options.build_executables and self.options.with_curl
        if Version(self.version) >= "8.1.0":
            tc.variables["NLOHMANN_JSON_ORIGIN"] = "external"
        tc.variables["CMAKE_MACOSX_BUNDLE"] = False
        if self.settings.os == "Linux":
            # Workaround for: https://github.com/conan-io/conan/issues/13560
            libdirs_host = [l for dependency in self.dependencies.host.values() for l in dependency.cpp_info.aggregated_components().libdirs]
            tc.variables["CMAKE_BUILD_RPATH"] = ";".join(libdirs_host)
        tc.cache_variables["CMAKE_POLICY_DEFAULT_CMP0077"] = "NEW"
        tc.generate()

        deps = CMakeDeps(self)
        deps.generate()

    def _patch_sources(self):
        apply_conandata_patches(self)

        cmakelists = os.path.join(self.source_folder, "CMakeLists.txt")

        replace_in_file(self, cmakelists, "/W4", "")

        # Fix up usage of SQLite3 finder outputs
        if Version(self.version) < "9.4.0":
            rm(self, "FindSqlite3.cmake", os.path.join(self.source_folder, "cmake"))
            replace_in_file(self, cmakelists, "SQLITE3_FOUND", "SQLite3_FOUND")
            replace_in_file(self, cmakelists, "SQLITE3_VERSION", "SQLite3_VERSION")
            replace_in_file(self, cmakelists, "find_package(Sqlite3 REQUIRED)", "find_package(SQLite3 REQUIRED)")

        # Let CMake install shared lib with a clean rpath !
        if "7.1.0" <= Version(self.version) < "9.0.0":
            replace_in_file(self, cmakelists, "set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)", "")

        # Aggressive workaround against SIP on macOS, to handle sqlite3 executable
        # linked to shared sqlite3 lib
        if is_apple_os(self):
            if Version(self.version) < "8.1.0":
                cmake_sqlite_call = "CMakeLists.txt"
                pattern = "${EXE_SQLITE3}"
            else:
                cmake_sqlite_call = "generate_proj_db.cmake"
                pattern = "\"${EXE_SQLITE3}\""

            lib_paths = self.dependencies.build["sqlite3"].cpp_info.libdirs
            replace_in_file(self,
                os.path.join(self.source_folder, "data", cmake_sqlite_call),
                f"COMMAND {pattern}",
                f"COMMAND ${{CMAKE_COMMAND}} -E env \"DYLD_LIBRARY_PATH={':'.join(lib_paths)}\" {pattern}"
            )

        # unvendor nlohmann_json
        if Version(self.version) < "8.1.0":
            rmdir(self, os.path.join(self.source_folder, "include", "proj", "internal", "nlohmann"))

        # Remove warning flags that are unfamiliar to GCC 5
        if Version(self.version) >= "9.0" and self.settings.compiler == "gcc" and Version(self.settings.compiler.version) < "8.0":
            replace_in_file(self, os.path.join(self.source_folder, "src", "CMakeLists.txt"), "${PROJ_C_WARN_FLAGS}", "")
            replace_in_file(self, os.path.join(self.source_folder, "src", "CMakeLists.txt"), "${PROJ_CXX_WARN_FLAGS}", "")

    def build(self):
        self._patch_sources()
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        copy(self, "COPYING", dst=os.path.join(self.package_folder, "licenses"), src=self.source_folder)
        cmake = CMake(self)
        cmake.install()
        # recover the data ... 9.1.0 saves into share/proj rather than res directly
        # the new PROJ_DATA_PATH can't seem to be controlled from conan.
        if Version(self.version) >= "9.1.0":
            rename(self, src=os.path.join(self.package_folder, "share", "proj"), dst=os.path.join(self.package_folder, "res"))
        # delete the rest of the deployed data
        rmdir(self, os.path.join(self.package_folder, "share"))
        rmdir(self, os.path.join(self.package_folder, "lib", "cmake"))
        rmdir(self, os.path.join(self.package_folder, "lib", "pkgconfig"))

    def package_info(self):
        proj_version = Version(self.version)
        cmake_config_filename = "proj" if proj_version >= "7.0.0" else "proj4"
        cmake_namespace = "PROJ" if proj_version >= "7.0.0" else "PROJ4"
        self.cpp_info.set_property("cmake_file_name", cmake_config_filename)
        self.cpp_info.set_property("cmake_target_name", f"{cmake_namespace}::proj")
        self.cpp_info.set_property("pkg_config_name", "proj")
        self.cpp_info.components["projlib"].set_property("cmake_target_name", f"{cmake_namespace}::proj")
        self.cpp_info.components["projlib"].set_property("pkg_config_name", "proj")

        self.cpp_info.components["projlib"].libs = collect_libs(self)
        if self.settings.os in ["Linux", "FreeBSD"]:
            self.cpp_info.components["projlib"].system_libs.append("m")
            if self.options.threadsafe:
                self.cpp_info.components["projlib"].system_libs.append("pthread")
        elif self.settings.os == "Windows":
            if proj_version >= "7.0.0":
                self.cpp_info.components["projlib"].system_libs.append("shell32")
            if proj_version >= "7.1.0":
                self.cpp_info.components["projlib"].system_libs.append("ole32")
        if not self.options.shared:
            libcxx = stdcpp_library(self)
            if libcxx:
                self.cpp_info.components["projlib"].system_libs.append(libcxx)
        self.cpp_info.components["projlib"].requires.extend(["nlohmann_json::nlohmann_json", "sqlite3::sqlite3"])
        if self.options.get_safe("with_tiff"):
            self.cpp_info.components["projlib"].requires.append("libtiff::libtiff")
        if self.options.get_safe("with_curl"):
            self.cpp_info.components["projlib"].requires.append("libcurl::libcurl")
        if Version(self.version) < "8.2.0":
            if self.options.shared and is_msvc(self):
                self.cpp_info.components["projlib"].defines.append("PROJ_MSVC_DLL_IMPORT")
        else:
            if not self.options.shared:
                self.cpp_info.components["projlib"].defines.append("PROJ_DLL=")

        # see https://proj.org/usage/environmentvars.html#envvar-PROJ_DATA
        proj_data_env_var_name = "PROJ_LIB" if Version(self.version) < "9.1.0" else "PROJ_DATA"
        res_path = os.path.join(self.package_folder, "res")
        self.runenv_info.prepend_path(proj_data_env_var_name, res_path)
        if self.options.build_executables:
            self.buildenv_info.prepend_path(proj_data_env_var_name, res_path)

