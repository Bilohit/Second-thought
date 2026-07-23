import { describe, it, expect } from "vitest";
import { isObj, arrayField, asArray } from "./jsonGuard";

describe("isObj", () => {
  it("accepts a plain object", () => {
    expect(isObj({ a: 1 })).toBe(true);
  });

  it("rejects null, arrays and primitives", () => {
    expect(isObj(null)).toBe(false);
    expect(isObj([1, 2])).toBe(false);
    expect(isObj("x")).toBe(false);
    expect(isObj(undefined)).toBe(false);
  });
});

describe("arrayField", () => {
  it("returns the array when the envelope is well-formed", () => {
    expect(arrayField<number>({ results: [1, 2] }, "results")).toEqual([1, 2]);
  });

  it("falls back when the field is missing or not an array", () => {
    expect(arrayField({}, "results")).toEqual([]);
    expect(arrayField({ results: "nope" }, "results")).toEqual([]);
    expect(arrayField({ results: null }, "results")).toEqual([]);
  });

  it("falls back when the body is not an object at all", () => {
    // The shapes a malformed/error body actually arrives as.
    expect(arrayField(null, "results")).toEqual([]);
    expect(arrayField("Internal Server Error", "results")).toEqual([]);
    expect(arrayField([1, 2, 3], "results")).toEqual([]);
  });

  it("honours an explicit fallback", () => {
    expect(arrayField({}, "results", [9])).toEqual([9]);
  });
});

describe("asArray", () => {
  it("passes an array through and replaces anything else", () => {
    expect(asArray([1])).toEqual([1]);
    expect(asArray({ a: 1 })).toEqual([]);
    expect(asArray(null)).toEqual([]);
  });
});
