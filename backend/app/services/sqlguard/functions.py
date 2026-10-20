"""Function allowlist for generated SQL.

Two lists, because sqlglot parses known functions into typed expression classes and unknown ones
into `exp.Anonymous` nodes:

- ALLOWED_FUNC_CLASSES: sqlglot class names (e.g. "Sum", "TimestampTrunc").
- ALLOWED_ANONYMOUS: lower-case DuckDB function names that sqlglot does not model.

Anything not listed is rejected. That deliberately excludes table functions (read_csv, glob,
range, query, ...), file / environment / settings access (getenv, current_setting, read_text),
catalog introspection (duckdb_*, current_database, version), sequence and error functions.
"""

from __future__ import annotations

ALLOWED_FUNC_CLASSES: frozenset[str] = frozenset(
    {
        # aggregates
        "Sum", "Avg", "Min", "Max", "Count", "CountIf", "Median", "Mode", "Stddev",
        "StddevSamp", "StddevPop", "Variance", "VariancePop", "Corr", "CovarPop", "CovarSamp",
        "PercentileCont", "PercentileDisc", "ApproxDistinct", "ApproxQuantile", "GroupConcat",
        "ArrayAgg", "LogicalAnd", "LogicalOr", "AnyValue", "ArgMax", "ArgMin", "First", "Last",
        "RegrSlope", "RegrIntercept", "RegrR2", "Kurtosis", "Skewness", "BitwiseAndAgg",
        "BitwiseOrAgg", "BitwiseXorAgg", "Quantile",
        # window
        "RowNumber", "Rank", "DenseRank", "PercentRank", "CumeDist", "Ntile", "Lag", "Lead",
        "FirstValue", "LastValue", "NthValue",
        # math
        "Abs", "Round", "Ceil", "Floor", "Sqrt", "Pow", "Exp", "Ln", "Log", "Sign", "Greatest",
        "Least", "Trunc", "Cbrt", "Pi", "Rand", "IsNan", "IsInf", "Factorial", "SafeDivide",
        "Degrees", "Radians", "Sin", "Cos", "Tan", "Asin", "Acos", "Atan", "Atan2",
        # string
        "Lower", "Upper", "Length", "Trim", "Substring", "Replace", "Concat", "ConcatWs",
        "SplitPart", "Left", "Right", "Pad", "Reverse", "StrPosition", "Contains", "StartsWith",
        "EndsWith", "RegexpLike", "RegexpILike", "RegexpReplace", "RegexpExtract",
        "RegexpExtractAll", "RegexpSplit", "Split", "Repeat", "Initcap", "Ascii", "Chr", "MD5",
        "Levenshtein", "JarowinklerSimilarity", "Format", "Translate", "Unicode", "ToChar",
        "Space", "Hex", "Unhex",
        # date / time
        "TimestampTrunc", "DateTrunc", "Extract", "Year", "Month", "Day", "DayOfWeek",
        "DayOfWeekIso", "DayOfMonth", "DayOfYear", "Week", "WeekOfYear", "Quarter", "Hour",
        "Minute", "Second", "Dayname", "Monthname", "TimeToUnix", "TimeToStr", "StrToTime",
        "StrToDate", "DateDiff", "DateAdd", "DateSub", "TimestampDiff", "TimestampAdd",
        "TimestampSub", "CurrentDate", "CurrentTimestamp", "CurrentTime", "DateFromParts",
        "TimestampFromParts", "LastDay", "Date", "UnixToTime", "DateBin", "DateStrToDate",
        "TsOrDsToDate", "TsOrDsAdd", "MakeInterval", "Timestamp", "ToDays",
        # conditional / casting / structure
        "Case", "If", "Cast", "TryCast", "Coalesce", "Nullif", "Exists", "Typeof", "Array",
        "Struct", "Columns", "ArrayContains", "ArraySize", "Transform", "ArrayFilter",
        "Flatten", "ArrayDistinct", "SortArray", "ArrayJoin", "ArrayToString", "Explode",
        "ArraySlice", "ArrayFirst", "ArrayLast", "ArrayReverse", "ArrayConcat", "ArrayUniqueAgg",
        "StructExtract", "JSONExtract", "JSONExtractScalar", "Uuid", "Map", "VarMap",
    }
)  # fmt: skip

ALLOWED_ANONYMOUS: frozenset[str] = frozenset(
    {
        "product", "entropy", "histogram", "fsum", "favg", "sumkahan", "bit_and", "bit_or",
        "even", "gcd", "lcm", "bit_count", "prefix", "suffix", "hash", "printf", "date_part",
        "datepart", "date_sub", "yearweek", "now", "age", "to_date", "list_sum", "list_avg",
        "list_min", "list_max", "list_count", "list_aggregate", "list_aggr", "list_reduce",
        "list_has_any", "list_has_all", "list_position", "list_extract", "list_element",
        "row", "strip_accents", "nfc_normalize", "ilike_escape", "like_escape", "isfinite",
        "epoch_ms", "epoch_us", "millisecond", "microsecond", "era", "decade", "century",
        "millennium", "isoyear", "weekday", "dayofmonth", "to_weeks", "to_months", "to_years",
        "to_hours", "to_minutes", "to_seconds", "to_milliseconds", "datesub", "datetrunc",
        "time_bucket", "make_time", "greatest_common_divisor", "least_common_multiple",
        "round_even", "roundbankers", "array_has", "array_position", "string_to_array",
        "regexp_full_match", "array_value", "list_slice", "list_concat", "list_reverse",
        "struct_extract", "map_extract", "element_at", "cardinality", "arbitrary", "mad",
        "kahan_sum", "approx_quantile", "reservoir_quantile", "quantile", "quantile_cont",
        "quantile_disc", "regr_count", "regr_avgx", "regr_avgy", "regr_sxx", "regr_syy",
        "regr_sxy", "trim", "split", "nullif", "iff", "concat", "list_distinct", "list_unique",
        "array_unique", "len", "bar", "format_bytes", "formatReadableSize", "to_base",
        "from_base", "ord", "unicode", "position", "contains", "least", "greatest",
    }
)  # fmt: skip
