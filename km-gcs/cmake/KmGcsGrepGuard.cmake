# Script-mode helper for kmgcs_forbid_symbols(). Runs as a POST_BUILD step.
#
# Inputs (passed with -D):
#   KMGCS_FILES     '|'-separated list of files to scan
#   KMGCS_PATTERNS  '|'-separated list of regexes that must not appear
#   KMGCS_TARGET    target name, for the message
#   KMGCS_REASON    human-readable reason, for the message

string(REPLACE "|" ";" _files "${KMGCS_FILES}")
string(REPLACE "|" ";" _patterns "${KMGCS_PATTERNS}")

set(_violations "")
foreach(_file IN LISTS _files)
    if(NOT EXISTS "${_file}")
        continue()
    endif()
    file(READ "${_file}" _content)
    # Comments are allowed to name what the layer must not use; only code counts.
    string(REGEX REPLACE "//[^\n]*" "" _content "${_content}")
    string(REGEX REPLACE "/\\*([^*]|\\*[^/])*\\*/" "" _content "${_content}")
    foreach(_pattern IN LISTS _patterns)
        if(_content MATCHES "${_pattern}")
            get_filename_component(_name "${_file}" NAME)
            list(APPEND _violations "${_name}: ${_pattern}")
        endif()
    endforeach()
endforeach()

if(_violations)
    list(JOIN _violations "\n    " _detail)
    message(FATAL_ERROR
        "LAYERING VIOLATION in '${KMGCS_TARGET}' -- ${KMGCS_REASON}:\n"
        "    ${_detail}\n"
        "  This layer must not name those symbols. Translate at the adapter\n"
        "  boundary instead. See km-gcs/docs/architecture/adr/0001-layering.md")
endif()
